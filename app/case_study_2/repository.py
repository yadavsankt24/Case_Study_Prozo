"""
Repositories: the only place that knows how data is stored in MongoDB.

Collections
    jobs               one document per verification run (status, progress, summary)
    employee_results   one document per wagesheet employee per job (PF + ESIC verdicts)
    ecr_only_members   ECR members that are not on the wagesheet

Results are stored per employee (not inside the job document) so that a
job with tens of thousands of employees stays well below MongoDB's 16 MB
document limit and the UI can filter / paginate on the server.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from app.case_study_2.models import CheckResult, EmployeeResult, VerificationReport


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain(value: Any) -> Any:
    """Convert enums / nested dataclass output into BSON-friendly values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class JobRepository:
    def __init__(self, db: Database):
        self.collection = db.jobs
        self.collection.create_index([("created_at", DESCENDING)])
        self.collection.create_index([("status", ASCENDING)])

    def create(self, job_id: str, label: str, input_files: dict, stored_paths: dict) -> dict:
        document = {
            "_id": job_id,
            "label": label,
            "status": JobStatus.QUEUED.value,
            "stage": "queued",
            "progress": 0,
            "message": "Waiting to start",
            "input_files": input_files,      # original file names shown to the user
            "stored_paths": stored_paths,    # where the uploads are kept on disk
            "summary": None,
            "warnings": [],
            "reconciliation": [],
            "error": None,
            "report_path": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.collection.insert_one(document)
        return document

    def get(self, job_id: str) -> Optional[dict]:
        return self.collection.find_one({"_id": job_id})

    def list_recent(self, limit: int = 20) -> list[dict]:
        return list(self.collection.find({}, {"stored_paths": 0}).sort("created_at", DESCENDING).limit(limit))

    def update_progress(self, job_id: str, stage: str, progress: int, message: str) -> None:
        self.collection.update_one(
            {"_id": job_id},
            {"$set": {"status": JobStatus.RUNNING.value, "stage": stage, "progress": progress,
                      "message": message, "updated_at": _now()}},
        )

    def mark_completed(self, job_id: str, report: VerificationReport, report_path: str) -> None:
        self.collection.update_one(
            {"_id": job_id},
            {"$set": {
                "status": JobStatus.COMPLETED.value,
                "stage": "completed",
                "progress": 100,
                "message": "Verification complete",
                "summary": report.summary(),
                "warnings": report.warnings,
                "reconciliation": [asdict(r) for r in report.reconciliation],
                "metadata": _plain(report.metadata),
                "report_path": report_path,
                "updated_at": _now(),
            }},
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        self.collection.update_one(
            {"_id": job_id},
            {"$set": {"status": JobStatus.FAILED.value, "stage": "failed", "message": error,
                      "error": error, "updated_at": _now()}},
        )

    def fail_interrupted_jobs(self) -> int:
        """Jobs left 'running' by a previous app process can never finish - say so honestly."""
        result = self.collection.update_many(
            {"status": {"$in": [JobStatus.QUEUED.value, JobStatus.RUNNING.value]}},
            {"$set": {"status": JobStatus.FAILED.value, "stage": "failed",
                      "error": "The server restarted while this job was running. Please upload again.",
                      "message": "Interrupted by a server restart", "updated_at": _now()}},
        )
        return result.modified_count


class ResultRepository:
    def __init__(self, db: Database):
        self.employees = db.employee_results
        self.ecr_only = db.ecr_only_members
        self.employees.create_index([("job_id", ASCENDING), ("row_number", ASCENDING)])
        self.employees.create_index([("job_id", ASCENDING), ("pf.status", ASCENDING)])
        self.employees.create_index([("job_id", ASCENDING), ("esic.status", ASCENDING)])
        self.ecr_only.create_index([("job_id", ASCENDING)])

    def save(self, job_id: str, report: VerificationReport) -> None:
        if report.employees:
            self.employees.insert_many([self._employee_document(job_id, e) for e in report.employees])
        if report.ecr_only:
            self.ecr_only.insert_many([{"job_id": job_id, **asdict(m)} for m in report.ecr_only])

    def find_employees(self, job_id: str, check: Optional[str] = None, status: Optional[str] = None,
                       search: Optional[str] = None, needs_review: bool = False,
                       skip: int = 0, limit: int = 100) -> tuple[list[dict], int]:
        query: dict[str, Any] = {"job_id": job_id}
        if check in ("pf", "esic") and status:
            query[f"{check}.status"] = status
        elif status:  # any check with this status
            query["$or"] = [{"pf.status": status}, {"esic.status": status}]
        if needs_review:
            query.setdefault("$and", []).append({"$or": [{"pf.needs_review": True}, {"esic.needs_review": True}]})
        if search:
            pattern = re.compile(re.escape(search.strip()), re.IGNORECASE)
            query.setdefault("$and", []).append(
                {"$or": [{"name": pattern}, {"uan": pattern}, {"ip_number": pattern}]})

        total = self.employees.count_documents(query)
        cursor = (self.employees.find(query, {"_id": 0})
                  .sort("row_number", ASCENDING).skip(skip).limit(limit))
        return list(cursor), total

    def all_employees(self, job_id: str) -> list[dict]:
        return list(self.employees.find({"job_id": job_id}, {"_id": 0}).sort("row_number", ASCENDING))

    def find_ecr_only(self, job_id: str) -> list[dict]:
        return list(self.ecr_only.find({"job_id": job_id}, {"_id": 0}))

    @staticmethod
    def _employee_document(job_id: str, employee: EmployeeResult) -> dict:
        row = employee.row
        return {
            "job_id": job_id,
            "row_number": row.row_number,
            "name": row.name,
            "uan": row.uan,
            "ip_number": row.ip_number,
            "agency": row.agency,
            "state": row.state,
            "pf": _check_document(employee.pf),
            "esic": _check_document(employee.esic),
        }


def _check_document(result: CheckResult) -> dict:
    return _plain(asdict(result))
