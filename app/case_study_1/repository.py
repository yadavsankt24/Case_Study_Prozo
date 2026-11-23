"""
MongoDB storage for Case Study 1.

Collections
    cs1_batches   one document per upload: status, totals, vision mode, timestamps
    cs1_records   one document per frame: where the frame is stored, its processing
                  state (pending / done) and its result (status, values, evidence, notes).
                  A reviewed record keeps the automatic result under "auto" for audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

BATCH_QUEUED, BATCH_RUNNING, BATCH_COMPLETED, BATCH_FAILED = "queued", "running", "completed", "failed"
STATE_PENDING, STATE_DONE = "pending", "done"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Cs1Repository:
    def __init__(self, db: Database):
        self.batches = db.cs1_batches
        self.records = db.cs1_records
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.batches.create_index([("created_at", DESCENDING)])
        self.records.create_index([("batch_id", ASCENDING), ("index", ASCENDING)])
        self.records.create_index([("batch_id", ASCENDING), ("state", ASCENDING)])

    # ------------------------------------------------------------------ batches

    def create_batch(self, batch_id: str, label: str, total: int, skipped: list[str],
                     vision_enabled: bool, vision_model: str) -> None:
        self.batches.insert_one({
            "_id": batch_id, "label": label, "total": total, "skipped": skipped,
            "vision_enabled": vision_enabled, "vision_model": vision_model if vision_enabled else None,
            "status": BATCH_QUEUED, "message": "Waiting to start", "error": None,
            "created_at": _now(), "updated_at": _now(), "completed_at": None,
        })

    def get_batch(self, batch_id: str) -> Optional[dict]:
        return self.batches.find_one({"_id": batch_id})

    def list_batches(self, limit: int = 20) -> list[dict]:
        return list(self.batches.find({}).sort("created_at", DESCENDING).limit(limit))

    def set_batch_status(self, batch_id: str, status: str, message: str, error: Optional[str] = None) -> None:
        update = {"status": status, "message": message, "error": error, "updated_at": _now()}
        if status == BATCH_COMPLETED:
            update["completed_at"] = _now()
        self.batches.update_one({"_id": batch_id}, {"$set": update})

    def delete_batch(self, batch_id: str) -> int:
        removed = self.records.delete_many({"batch_id": batch_id}).deleted_count
        self.batches.delete_one({"_id": batch_id})
        return removed

    def unfinished_batches(self) -> list[dict]:
        return list(self.batches.find({"status": {"$in": [BATCH_QUEUED, BATCH_RUNNING]}}))

    def status_counts(self, batch_id: str) -> dict[str, int]:
        """Frames per status for one batch (finished frames only)."""
        pipeline = [{"$match": {"batch_id": batch_id, "state": STATE_DONE}},
                    {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        return {row["_id"]: row["n"] for row in self.records.aggregate(pipeline)}

    def count(self, batch_id: str, **query) -> int:
        return self.records.count_documents({"batch_id": batch_id, **query})

    # ------------------------------------------------------------------ records

    def add_records(self, batch_id: str, frames: list[dict]) -> None:
        """frames: [{index, filename, stored_path}]"""
        if frames:
            self.records.insert_many([{
                "_id": f"{batch_id}-{f['index']:05d}", "batch_id": batch_id, "index": f["index"],
                "filename": f["filename"], "stored_path": f["stored_path"], "thumb_path": None,
                "state": STATE_PENDING, "status": None, "reviewed": False, "created_at": _now(),
            } for f in frames])

    def get_record(self, record_id: str) -> Optional[dict]:
        return self.records.find_one({"_id": record_id})

    def records_for(self, batch_id: str, status: Optional[str] = None, flagged_only: bool = False) -> list[dict]:
        query: dict = {"batch_id": batch_id}
        if status:
            query["status"] = status
        elif flagged_only:
            query["state"] = STATE_DONE
            query["status"] = {"$ne": "OK"}
        return list(self.records.find(query).sort("index", ASCENDING))

    def pending_records(self, batch_id: str) -> list[dict]:
        return list(self.records.find({"batch_id": batch_id, "state": STATE_PENDING}).sort("index", ASCENDING))

    def save_result(self, record_id: str, result: dict, thumb_path: Optional[str]) -> None:
        self.records.update_one({"_id": record_id}, {"$set": {
            **result, "thumb_path": thumb_path, "state": STATE_DONE, "processed_at": _now()}})

    def mark_pending(self, record_ids: list[str]) -> None:
        self.records.update_many({"_id": {"$in": record_ids}}, {"$set": {"state": STATE_PENDING}})

    def add_note(self, record_id: str, note: str) -> None:
        self.records.update_one({"_id": record_id}, {"$addToSet": {"notes": note}})

    def save_review(self, record_id: str, changes: dict, auto_snapshot: Optional[dict]) -> None:
        update: dict = {"$set": {**changes, "reviewed": True, "reviewed_at": _now()}}
        if auto_snapshot is not None:
            update["$set"]["auto"] = auto_snapshot
        self.records.update_one({"_id": record_id}, update)
