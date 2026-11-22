"""
Case Study 3 workflow: a pipeline of small, single-purpose agents.

    IngestAgent    read the CSV / Excel and the target ranges, skip bad rows with warnings
    PnLAgent       calculate cost %, CM1, CM2 and the day colour            (deterministic)
    RuleAgent      flag cost lines and margins outside target, rank by ₹    (deterministic)
    InsightAgent   plain-English insight + recommended action per flagged day
    MemoryAgent    store every FC-day in MongoDB (history for trends and the dashboard)
    ReportAgent    write the Excel report
    DigestAgent    build each FC's colour-coded digest for its latest day (optionally
                   phrased by an LLM, fact-checked) and deliver it by email / outbox

Each agent is a method with one job; `process_run` runs them in order and reports
progress after each. Only the InsightAgent's optional LLM step is non-deterministic,
and it can never change a number, colour or flag.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from app.shared.llm import LLMClient, NoLLM
from app.config import Settings
from app.shared.errors import InputError
from app.case_study_3.digest import Delivery, Digest, build_digest, create_notifier, load_managers
from app.case_study_3.engine import evaluate_day, scenario_of
from app.case_study_3.ingest import read_fc_data
from app.case_study_3.insights import polish_with_llm, severity_counts, write_insight
from app.case_study_3.models import DayResult, IngestResult, Override
from app.case_study_3.report import write_report
from app.case_study_3.repository import RUN_QUEUED, RUN_RUNNING, Cs3Repository

log = logging.getLogger(__name__)


@dataclass
class RunOptions:
    fc_name: str = "FC-01"
    start_date: Optional[str] = None
    send_digests: bool = False


class Cs3Service:
    def __init__(self, settings: Settings, repo: Cs3Repository, llm: Optional[LLMClient] = None,
                 base_url: str = "http://localhost:8000"):
        self.settings = settings
        self.repo = repo
        self.llm = llm or NoLLM()
        self.base_url = base_url
        self.notifier = create_notifier(settings)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cs3")

    # ------------------------------------------------------------------ background runs

    def submit(self, run_id: str, path: str, options: RunOptions) -> None:
        self._executor.submit(self.process_run, run_id, path, options)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def process_run(self, run_id: str, path: str, options: RunOptions) -> None:
        progress = lambda stage, pct, msg: self.repo.update_progress(run_id, stage, pct, msg)  # noqa: E731
        try:
            progress("ingest", 10, "Reading the file")
            data = self.ingest_agent(path, options)

            progress("pnl", 30, f"Calculating P&L for {len(data.rows)} FC-days")
            days = self.pnl_and_rule_agents(data)

            progress("insights", 55, "Writing insights")
            self.insight_agent(days)

            progress("memory", 70, "Saving to history")
            self.repo.save_days(run_id, days)

            progress("report", 80, "Writing the Excel report")
            report_path = write_report(days, data.targets, data.warnings,
                                       self.settings.report_dir / f"cs3_{run_id}.xlsx")

            sent = []
            if options.send_digests:
                progress("digest", 90, "Sending digests to FC managers")
                sent = self.send_digests(fcs={d.fc for d in days})

            self.repo.complete_run(run_id, self._summary(days, data, sent), data.warnings, str(report_path))
        except InputError as error:
            self.repo.fail_run(run_id, error.message)
        except Exception:
            reference = uuid.uuid4().hex[:8]
            log.exception("CS3 run %s failed (ref %s)", run_id, reference)
            self.repo.fail_run(run_id, f"Something went wrong while processing the file (reference {reference}).")

    # ------------------------------------------------------------------ agents

    def ingest_agent(self, path: str, options: RunOptions) -> IngestResult:
        return read_fc_data(path, default_fc=options.fc_name, start_date=options.start_date)

    def pnl_and_rule_agents(self, data: IngestResult) -> list[DayResult]:
        overrides = self.repo.list_overrides()
        return [evaluate_day(row, data.targets, overrides) for row in data.rows]

    def insight_agent(self, days: list[DayResult]) -> None:
        for day in days:
            day.insight, day.action = write_insight(day)

    def digest_agent(self, fc: str, day: Optional[date] = None) -> Optional[Digest]:
        """Build the digest for one FC (latest stored day unless a date is given)."""
        if day is None:
            latest = self.repo.latest_dates().get(fc)
            if not latest:
                return None
            day = date.fromisoformat(latest)
        doc = self.repo.get_day(fc, day)
        if not doc:
            return None
        history = self.repo.history(fc, day, limit=30)
        insight, mode = polish_with_llm(doc["insight"], self.llm)
        manager = load_managers(self.settings.cs3_managers_file).get(fc) or {
            "manager": "", "email": self.settings.cs3_default_manager_email}
        return build_digest(doc, history, manager, insight, mode, f"{self.base_url}/case-study-3/dashboard")

    # ------------------------------------------------------------------ digests

    def send_digests(self, fcs: Optional[set[str]] = None, day: Optional[date] = None,
                     skip_already_sent: bool = False) -> list[dict]:
        targets = sorted(fcs or self.repo.latest_dates().keys())
        records = []
        for fc in targets:
            digest = self.digest_agent(fc, day)
            if digest is None:
                continue
            if skip_already_sent and self.repo.digest_sent(fc, digest.day):
                continue
            delivery: Delivery = self.notifier.send(digest)
            record = {"fc": fc, "date": digest.day, "colour": digest.colour, "subject": digest.subject,
                      "recipient": digest.recipient, "manager": digest.manager, "channel": delivery.channel,
                      "status": delivery.status, "detail": delivery.detail, "insight_mode": digest.insight_mode}
            self.repo.log_digest(record)
            records.append(record)
        return records

    # ------------------------------------------------------------------ delete

    def delete_run(self, run_id: str) -> Optional[int]:
        """Delete an analysis: its record, uploaded file, report and stored days. None if not found."""
        run = self.repo.get_run(run_id)
        if not run:
            return None
        if run["status"] in (RUN_QUEUED, RUN_RUNNING):
            raise InputError("This analysis is still processing. Please wait until it finishes before deleting it.")
        for key in ("stored_path", "report_path"):
            if run.get(key):
                Path(run[key]).unlink(missing_ok=True)
        return self.repo.delete_run(run_id)

    # ------------------------------------------------------------------ dashboard / overrides

    def dashboard(self, last_n_dates: int = 31) -> dict:
        docs = self.repo.dashboard_days(last_n_dates)
        fcs = sorted({d["fc"] for d in docs})
        dates = sorted({d["date"] for d in docs})
        latest = {fc: max((d for d in docs if d["fc"] == fc), key=lambda d: d["date"]) for fc in fcs}
        return {
            "fcs": fcs,
            "dates": dates,
            "cells": [{"fc": d["fc"], "date": d["date"], "colour": d["colour"], "cm2_pct": d["cm2_pct"],
                       "cm1_pct": d["cm1_pct"], "insight": d["insight"], "flags": len(d["anomalies"])} for d in docs],
            "latest": {fc: {"date": doc["date"], "colour": doc["colour"], "cm2_pct": doc["cm2_pct"],
                            "insight": doc["insight"]} for fc, doc in latest.items()},
            "colour_counts": dict(Counter(d["colour"] for d in docs)),
        }

    def add_override(self, fc: str, line_item: str, date_from: date, date_to: date, note: str) -> None:
        if date_to < date_from:
            raise InputError("The end date of a known issue cannot be before its start date.")
        self.repo.add_override(Override(fc, line_item, date_from, date_to, note.strip() or "known issue"))

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _summary(days: list[DayResult], data: IngestResult, sent: list[dict]) -> dict:
        dates = sorted({d.day for d in days})
        return {
            "fc_days": len(days),
            "fcs": sorted({d.fc for d in days}),
            "date_from": dates[0].isoformat(),
            "date_to": dates[-1].isoformat(),
            "colours": {c: sum(1 for d in days if d.colour.value == c) for c in ("Red", "Yellow", "Green", "Blue")},
            "scenarios": dict(Counter(scenario_of(d) for d in days)),
            "anomalies": sum(len(d.anomalies) for d in days),
            "severity": severity_counts(days),
            "targets_source": data.targets_source,
            "digests": [{k: r[k] for k in ("fc", "date", "status", "channel")} for r in sent],
        }


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def save_upload(folder: Path, run_id: str, filename: str, content: bytes) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"cs3_{run_id}{Path(filename).suffix.lower()}"
    path.write_bytes(content)
    return str(path)
