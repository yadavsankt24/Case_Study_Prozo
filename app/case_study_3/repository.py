"""
MongoDB storage for Case Study 3.

Collections
    cs3_runs        one document per upload (status, progress, summary, warnings, report path)
    cs3_days        one document per FC per date - the system's MEMORY. Upserted, so a
                    later upload of the same FC-day replaces it and history builds up
                    across uploads (used for trends and the central dashboard).
    cs3_overrides   manager "known issue" notes; matching anomalies are not alerted again
    cs3_digests     log of every digest built / sent (channel, recipient, status)

Dates are stored as ISO strings (YYYY-MM-DD): they sort correctly and serialise to JSON as-is.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Optional

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from app.case_study_3.models import DayResult, Override

RUN_QUEUED, RUN_RUNNING, RUN_COMPLETED, RUN_FAILED = "queued", "running", "completed", "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def day_to_document(day: DayResult, run_id: str) -> dict:
    return {
        "fc": day.fc,
        "date": day.day.isoformat(),
        "run_id": run_id,
        "revenue": day.revenue,
        "costs": day.costs,
        "pct": day.pct,
        "cm1": day.cm1, "cm1_pct": day.cm1_pct,
        "cm2": day.cm2, "cm2_pct": day.cm2_pct,
        "colour": day.colour.value,
        "insight": day.insight,
        "action": day.action,
        "anomalies": [
            {**asdict(a), "day": a.day.isoformat(), "severity": a.severity.value} for a in day.anomalies
        ],
        "updated_at": _now(),
    }


class Cs3Repository:
    def __init__(self, db: Database):
        self.runs = db.cs3_runs
        self.days = db.cs3_days
        self.overrides = db.cs3_overrides
        self.digests = db.cs3_digests
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.runs.create_index([("created_at", DESCENDING)])
        self.days.create_index([("fc", ASCENDING), ("date", ASCENDING)], unique=True)
        self.days.create_index([("run_id", ASCENDING)])
        self.days.create_index([("date", DESCENDING)])
        self.digests.create_index([("fc", ASCENDING), ("date", ASCENDING)])

    # ------------------------------------------------------------------ runs

    def create_run(self, run_id: str, filename: str, stored_path: str, options: dict) -> None:
        self.runs.insert_one({
            "_id": run_id, "filename": filename, "stored_path": stored_path, "options": options,
            "status": RUN_QUEUED, "stage": "queued", "progress": 0, "message": "Waiting to start",
            "summary": None, "warnings": [], "error": None, "report_path": None,
            "created_at": _now(), "updated_at": _now(),
        })

    def get_run(self, run_id: str) -> Optional[dict]:
        return self.runs.find_one({"_id": run_id})

    def list_runs(self, limit: int = 20) -> list[dict]:
        return list(self.runs.find({}, {"stored_path": 0}).sort("created_at", DESCENDING).limit(limit))

    def update_progress(self, run_id: str, stage: str, progress: int, message: str) -> None:
        self.runs.update_one({"_id": run_id}, {"$set": {
            "status": RUN_RUNNING, "stage": stage, "progress": progress, "message": message, "updated_at": _now()}})

    def complete_run(self, run_id: str, summary: dict, warnings: list[str], report_path: str) -> None:
        self.runs.update_one({"_id": run_id}, {"$set": {
            "status": RUN_COMPLETED, "stage": "completed", "progress": 100, "message": "Analysis complete",
            "summary": summary, "warnings": warnings, "report_path": report_path, "updated_at": _now()}})

    def fail_run(self, run_id: str, error: str) -> None:
        self.runs.update_one({"_id": run_id}, {"$set": {
            "status": RUN_FAILED, "stage": "failed", "message": error, "error": error, "updated_at": _now()}})

    def delete_run(self, run_id: str) -> int:
        """
        Delete a run and the FC-days it wrote. Days that a later upload has since
        replaced belong to that later run and are kept. Returns the number of days removed.
        """
        removed = self.days.delete_many({"run_id": run_id}).deleted_count
        self.runs.delete_one({"_id": run_id})
        return removed

    def fail_interrupted_runs(self) -> int:
        return self.runs.update_many(
            {"status": {"$in": [RUN_QUEUED, RUN_RUNNING]}},
            {"$set": {"status": RUN_FAILED, "stage": "failed", "updated_at": _now(),
                      "error": "The server restarted while this run was in progress. Please upload again."}},
        ).modified_count

    # ------------------------------------------------------------------ days (memory)

    def save_days(self, run_id: str, days: list[DayResult]) -> None:
        for day in days:
            self.days.replace_one({"fc": day.fc, "date": day.day.isoformat()}, day_to_document(day, run_id),
                                  upsert=True)

    def days_for_run(self, run_id: str, fc: Optional[str] = None, colour: Optional[str] = None) -> list[dict]:
        query: dict = {"run_id": run_id}
        if fc:
            query["fc"] = fc
        if colour:
            query["colour"] = colour
        return list(self.days.find(query, {"_id": 0}).sort([("fc", ASCENDING), ("date", ASCENDING)]))

    def history(self, fc: str, up_to: date, limit: int = 30) -> list[dict]:
        """Most recent days for one FC up to and including a date, newest first."""
        return list(self.days.find({"fc": fc, "date": {"$lte": up_to.isoformat()}}, {"_id": 0})
                    .sort("date", DESCENDING).limit(limit))

    def get_day(self, fc: str, day: date) -> Optional[dict]:
        return self.days.find_one({"fc": fc, "date": day.isoformat()}, {"_id": 0})

    def latest_dates(self) -> dict[str, str]:
        """Latest stored date for every FC."""
        latest: dict[str, str] = {}
        for doc in self.days.find({}, {"fc": 1, "date": 1, "_id": 0}):
            if doc["date"] > latest.get(doc["fc"], ""):
                latest[doc["fc"]] = doc["date"]
        return latest

    def dashboard_days(self, last_n_dates: int = 31) -> list[dict]:
        """Each FC's own most recent N days (FCs may report different date ranges)."""
        result: list[dict] = []
        for fc in sorted(self.days.distinct("fc")):
            recent = list(self.days.find({"fc": fc}, {"_id": 0, "costs": 0}).sort("date", DESCENDING).limit(last_n_dates))
            result.extend(reversed(recent))
        return result

    # ------------------------------------------------------------------ overrides

    def add_override(self, override: Override) -> None:
        self.overrides.insert_one({**asdict(override), "date_from": override.date_from.isoformat(),
                                   "date_to": override.date_to.isoformat(), "created_at": _now()})

    def list_overrides(self) -> list[Override]:
        return [
            Override(fc=o["fc"], line_item=o["line_item"], date_from=date.fromisoformat(o["date_from"]),
                     date_to=date.fromisoformat(o["date_to"]), note=o.get("note", ""))
            for o in self.overrides.find({}, {"_id": 0})
        ]

    def override_documents(self) -> list[dict]:
        return [{**o, "id": str(o.pop("_id"))} for o in self.overrides.find({}).sort("created_at", DESCENDING)]

    def delete_override(self, override_id: str) -> bool:
        from bson import ObjectId
        try:
            return self.overrides.delete_one({"_id": ObjectId(override_id)}).deleted_count == 1
        except Exception:
            return False

    # ------------------------------------------------------------------ digests

    def log_digest(self, record: dict) -> None:
        self.digests.insert_one({**record, "created_at": _now()})

    def digests_for(self, day: Optional[str] = None, limit: int = 50) -> list[dict]:
        query = {"date": day} if day else {}
        return list(self.digests.find(query, {"_id": 0, "html": 0}).sort("created_at", DESCENDING).limit(limit))

    def digest_sent(self, fc: str, day: str) -> bool:
        return self.digests.count_documents({"fc": fc, "date": day, "status": {"$in": ["sent", "saved"]}}) > 0
