"""
End-to-end verification pipeline (framework-free).

    validate -> read wagesheet -> parse PF ECR -> parse ESIC ECR
             -> reconcile totals -> verify employees -> VerificationReport

Used by the background job runner (web app), the CLI and the tests, so the
web layer contains no business logic at all.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.case_study_2 import rules
from app.case_study_2.matching.verifier import ContributionVerifier
from app.case_study_2.models import EsicEcrDocument, PfEcrDocument, ReconciliationCheck, VerificationReport
from app.case_study_2.parsers.esic_ecr import parse_esic_ecr
from app.case_study_2.parsers.pf_ecr import parse_pf_ecr
from app.case_study_2.parsers.wagesheet import read_wagesheet
from app.case_study_2.validation import validate_inputs

# (stage, percent 0-100, message)
ProgressFn = Callable[[str, int, str], None]


def _no_progress(stage: str, percent: int, message: str) -> None:
    pass


class VerificationPipeline:
    def __init__(self, verifier: Optional[ContributionVerifier] = None, progress: ProgressFn = _no_progress):
        self.verifier = verifier or ContributionVerifier()
        self.progress = progress

    def run(self, wagesheet_path: str, pf_path: str, esic_path: str) -> VerificationReport:
        started = time.perf_counter()

        self.progress("validating", 5, "Checking the uploaded files")
        validate_inputs(wagesheet_path, pf_path, esic_path)

        self.progress("reading_wagesheet", 10, "Reading the wagesheet")
        rows = read_wagesheet(wagesheet_path)

        pf_doc = parse_pf_ecr(pf_path, on_page=self._page_progress("parsing_pf", "PF ECR", 15, 45))
        esic_doc = parse_esic_ecr(esic_path, on_page=self._page_progress("parsing_esic", "ESIC ECR", 45, 75))

        self.progress("reconciling", 78, "Reconciling parsed totals with ECR totals")
        reconciliation = reconcile(pf_doc, esic_doc)

        self.progress("matching", 85, f"Matching {len(rows)} employees")
        outcome = self.verifier.verify(rows, pf_doc, esic_doc)

        warnings = outcome.warnings + _wage_month_warnings(pf_doc, esic_doc)
        warnings += [f"{r.document}: {r.metric} - {r.note}" for r in reconciliation if not r.ok]

        metadata = {
            "files": {
                "wagesheet": Path(wagesheet_path).name,
                "pf_ecr": Path(pf_path).name,
                "esic_ecr": Path(esic_path).name,
            },
            "pf_header": pf_doc.header,
            "esic_header": esic_doc.header,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_seconds": round(time.perf_counter() - started, 2),
            "amount_tolerance": rules.AMOUNT_TOLERANCE_RUPEES,
        }
        return VerificationReport(
            employees=outcome.employees,
            ecr_only=outcome.ecr_only,
            reconciliation=reconciliation,
            warnings=warnings,
            metadata=metadata,
            pf_log=pf_doc.log,
            esic_log=esic_doc.log,
        )

    def _page_progress(self, stage: str, label: str, start: int, end: int):
        def callback(page: int, total: int) -> None:
            percent = start + int((end - start) * page / max(total, 1))
            self.progress(stage, percent, f"Reading {label}: page {page} of {total}")
        return callback


def reconcile(pf_doc: PfEcrDocument, esic_doc: EsicEcrDocument) -> list[ReconciliationCheck]:
    """Compare what we parsed with the totals printed on the ECRs."""
    tolerance = rules.RECONCILIATION_TOLERANCE_RUPEES
    checks: list[ReconciliationCheck] = []

    def add(document: str, metric: str, printed: Optional[float], parsed: float, is_count: bool = False):
        if printed is None:
            checks.append(ReconciliationCheck(document, metric, None, parsed, True,
                                              "total not printed on the ECR, could not cross-check"))
            return
        ok = abs(printed - parsed) <= (0 if is_count else tolerance)
        note = "matches" if ok else f"printed {printed:,.0f} but parsed {parsed:,.0f} - some rows may be missed"
        checks.append(ReconciliationCheck(document, metric, printed, parsed, ok, note))

    add("PF ECR", "Member count", pf_doc.header.get("total_members"), len(pf_doc.members), is_count=True)
    add("PF ECR", "Total EPF (EE) contribution", pf_doc.header.get("total_epf_contribution"),
        sum(m.ee_share or 0 for m in pf_doc.members))
    add("ESIC ECR", "Total IP contribution", esic_doc.header.get("total_ip_contribution"),
        sum(m.ip_contribution or 0 for m in esic_doc.members))
    add("ESIC ECR", "Total monthly wages", esic_doc.header.get("total_monthly_wages"),
        sum(m.wages or 0 for m in esic_doc.members))
    return checks


def _wage_month_warnings(pf_doc: PfEcrDocument, esic_doc: EsicEcrDocument) -> list[str]:
    pf_month, esic_month = pf_doc.header.get("wage_month"), esic_doc.header.get("wage_month")
    if pf_month and esic_month and pf_month != esic_month:
        return [f"Wage month differs between files: PF ECR is {pf_month}, ESIC ECR is {esic_month}."]
    return []
