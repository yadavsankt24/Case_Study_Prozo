"""
Case Study 1 workflow: batches of frames read in the background.

    create_batch    validate the upload, unpack ZIPs, store every frame, queue the batch
    process_record  run the per-frame pipeline (pipeline.py) and save the record
    finish_batch    when the last frame is done: mark duplicate AWBs, close the batch
    review_record   a person confirms, corrects or keeps a flag; the automatic result is kept
    rerun           send frames back through the pipeline (e.g. after a Gemini outage)

Frames are processed by a small thread pool. The vision agent has its own rate limiter,
so the free-tier limit holds however many workers run.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import threading
import time
import uuid
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from pymongo.errors import ConnectionFailure

from app.case_study_1 import rules
from app.case_study_1.export import records_to_csv
from app.case_study_1.image_checks import make_thumbnail
from app.case_study_1.models import Status
from app.case_study_1.overlay_parser import normalise_awb
from app.case_study_1.pipeline import process_frame
from app.case_study_1.repository import (BATCH_COMPLETED, BATCH_QUEUED, BATCH_RUNNING,
                                         STATE_PENDING, Cs1Repository)
from app.case_study_1.vision import VisionReader
from app.config import Settings
from app.shared.errors import InputError

log = logging.getLogger(__name__)

DATASET_SUFFIX = re.compile(r"_(png|jpe?g|webp|bmp)\.rf\.[A-Za-z0-9]+(?=\.[A-Za-z]+$)", re.IGNORECASE)


def display_name(filename: str) -> str:
    """'Half shipment captured_png.rf.WNrel…png' -> 'Half shipment captured.png' (dataset export suffix removed)."""
    return DATASET_SUFFIX.sub("", Path(filename).name)


def new_batch_id() -> str:
    return uuid.uuid4().hex[:12]


class Cs1Service:
    def __init__(self, settings: Settings, repo: Cs1Repository, vision: Optional[VisionReader] = None):
        self.settings = settings
        self.repo = repo
        self.vision = vision
        self._executor = ThreadPoolExecutor(max_workers=max(settings.cs1_workers, 1), thread_name_prefix="cs1")
        self._finish_lock = threading.Lock()

    @property
    def mode(self) -> dict:
        return {"vision": self.vision is not None,
                "model": self.settings.cs1_vision_model if self.vision is not None else None}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ upload

    def create_batch(self, uploads: list[tuple[str, bytes]], label: str = "") -> dict:
        frames, skipped = self._collect_frames(uploads)
        if not frames:
            detail = f" Skipped: {', '.join(skipped[:5])}." if skipped else ""
            raise InputError("No images found in the upload. Choose JPG / PNG frames or a ZIP of them." + detail)

        batch_id = new_batch_id()
        folder = self.settings.cs1_frame_dir / batch_id
        folder.mkdir(parents=True, exist_ok=True)
        stored = []
        for index, (name, content) in enumerate(frames, start=1):
            path = folder / f"{index:05d}{Path(name).suffix.lower()}"
            path.write_bytes(content)
            stored.append({"index": index, "filename": display_name(name), "stored_path": str(path)})

        label = label.strip() or (frames[0][0] if len(uploads) == 1 else f"{len(frames)} frames")
        self.repo.create_batch(batch_id, display_name(label), len(stored), skipped,
                               vision_enabled=self.vision is not None, vision_model=self.settings.cs1_vision_model)
        self.repo.add_records(batch_id, stored)
        self.submit(batch_id)
        return {"batch_id": batch_id, "frames": len(stored), "skipped": skipped}

    def _collect_frames(self, uploads: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
        """Images from the upload, including every image inside ZIP files (any folder)."""
        frames, skipped = [], []
        for name, content in uploads:
            suffix = Path(name).suffix.lower()
            if suffix == ".zip":
                frames_in_zip, skipped_in_zip = self._unzip(name, content)
                frames += frames_in_zip
                skipped += skipped_in_zip
            elif suffix in rules.IMAGE_EXTENSIONS:
                frames.append((name, content))       # unreadable images still get a row (INVALID_IMAGE)
            else:
                skipped.append(name)
        return frames, skipped

    @staticmethod
    def _unzip(name: str, content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise InputError(f"'{name}' is not a valid ZIP file.")
        frames, skipped = [], []
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            entry = Path(info.filename)
            if info.is_dir() or "__MACOSX" in entry.parts or entry.name.startswith("."):
                continue
            if entry.suffix.lower() in rules.IMAGE_EXTENSIONS:
                frames.append((entry.name, archive.read(info)))
            else:
                skipped.append(f"{name}/{info.filename}")
        return frames, skipped

    # ------------------------------------------------------------------ processing

    def submit(self, batch_id: str) -> None:
        for record in self.repo.pending_records(batch_id):
            self._executor.submit(self.process_record, batch_id, record["_id"])

    def resume_unfinished(self) -> int:
        """After a restart: continue batches that were still running. Finished frames are not re-read."""
        batches = self.repo.unfinished_batches()
        for batch in batches:
            if self.repo.count(batch["_id"], state=STATE_PENDING):
                self.submit(batch["_id"])
            else:
                self.finish_batch(batch["_id"])
        return len(batches)

    def process_record(self, batch_id: str, record_id: str) -> None:
        record = self.repo.get_record(record_id)
        if not record or record.get("state") != STATE_PENDING:
            return
        batch = self.repo.get_batch(batch_id)
        if batch and batch["status"] == BATCH_QUEUED:
            self.repo.set_batch_status(batch_id, BATCH_RUNNING, "Reading frames")
        try:
            content = Path(record["stored_path"]).read_bytes()
            result, image = process_frame(content, self.vision)
            thumb = None
            if image is not None:
                thumb_path = Path(record["stored_path"]).with_suffix(".thumb.jpg")
                thumb_path.write_bytes(make_thumbnail(image))
                thumb = str(thumb_path)
            data = result.to_dict()
        except Exception:
            reference = uuid.uuid4().hex[:8]
            log.exception("CS1 frame %s failed (ref %s)", record_id, reference)
            data = {"status": Status.PROCESSING_ERROR.value, "confidence": "low", "notes": [],
                    "status_reason": f"Something went wrong while reading this frame (reference {reference})."}
            thumb = None
        self._with_retry(lambda: self.repo.save_result(record_id, data, thumb))
        if not self._with_retry(lambda: self.repo.count(batch_id, state=STATE_PENDING)):
            self.finish_batch(batch_id)

    @staticmethod
    def _with_retry(action, attempts: int = 4, wait_seconds: float = 1.0):
        """Run a database call again after a temporary connection error (network / TLS drop)."""
        for attempt in range(1, attempts + 1):
            try:
                return action()
            except ConnectionFailure:
                if attempt == attempts:
                    raise
                log.warning("Database not reachable, retrying (%d/%d)", attempt, attempts - 1)
                time.sleep(wait_seconds * attempt)

    def finish_batch(self, batch_id: str) -> None:
        with self._finish_lock:
            batch = self.repo.get_batch(batch_id)
            if not batch or batch["status"] == BATCH_COMPLETED or self.repo.count(batch_id, state=STATE_PENDING):
                return
            self._mark_duplicates(batch_id)
            counts = self.repo.status_counts(batch_id)
            self.repo.set_batch_status(batch_id, BATCH_COMPLETED,
                                       f"{counts.get('OK', 0)} of {sum(counts.values())} frames read automatically")

    def _mark_duplicates(self, batch_id: str) -> None:
        records = self.repo.records_for(batch_id)
        awbs = Counter(r["awb"] for r in records if r.get("awb"))
        for record in records:
            if record.get("awb") and awbs[record["awb"]] > 1:
                self.repo.add_note(record["_id"], f"duplicate AWB: appears in {awbs[record['awb']]} frames of this batch")

    def rerun(self, batch_id: str, record_id: Optional[str] = None) -> int:
        """Re-read one frame, or every PROCESSING_ERROR frame of the batch."""
        batch = self._require_batch(batch_id)
        if record_id:
            ids = [record_id]
        else:
            ids = [r["_id"] for r in self.repo.records_for(batch_id, status=Status.PROCESSING_ERROR.value)]
        if not ids:
            return 0
        self.repo.mark_pending(ids)
        if batch["status"] == BATCH_COMPLETED:
            self.repo.set_batch_status(batch_id, BATCH_RUNNING, f"Re-reading {len(ids)} frame(s)")
        self.submit(batch_id)
        return len(ids)

    # ------------------------------------------------------------------ review

    def review_record(self, record_id: str, action: str, values: dict, note: str = "") -> dict:
        """
        action: "confirm"   accept the frame as OK with the values shown (corrected if edited)
                "keep_flag" keep the automatic status, mark as reviewed
        The first review stores the automatic result under "auto".
        """
        record = self.repo.get_record(record_id)
        if not record:
            raise InputError("This frame no longer exists.")
        if record.get("state") == STATE_PENDING:
            raise InputError("This frame is still being read. Try again in a moment.")
        snapshot = None if record.get("reviewed") else {
            k: record.get(k) for k in ("status", "status_reason", "awb", "length_cm", "width_cm", "height_cm",
                                       "weight_kg", "confidence")}
        changes: dict = {}
        if action == "confirm":
            changes = self._validated_values(values)
            changes.update(status=Status.OK.value, status_reason="Confirmed by a reviewer.")
        elif action != "keep_flag":
            raise InputError("Unknown review action.")
        notes = list(record.get("notes") or [])
        if note.strip():
            notes.append(f"reviewer: {note.strip()}")
        changes["notes"] = notes
        self.repo.save_review(record_id, changes, snapshot)
        return self.repo.get_record(record_id)

    @staticmethod
    def _validated_values(values: dict) -> dict:
        awb = normalise_awb(values.get("awb"))
        if not awb:
            raise InputError("Enter a valid AWB (8-20 letters or digits) to confirm this frame.", field="awb")
        clean: dict = {"awb": awb}
        for key, (low, high), unit in [("length_cm", rules.DIMENSION_RANGE_CM, "cm"), ("width_cm", rules.DIMENSION_RANGE_CM, "cm"),
                                       ("height_cm", rules.DIMENSION_RANGE_CM, "cm"), ("weight_kg", rules.WEIGHT_RANGE_KG, "kg")]:
            raw = values.get(key)
            if raw in (None, ""):
                clean[key] = None
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise InputError(f"{key.replace('_', ' ')} must be a number.", field=key)
            if not low <= number <= high:
                raise InputError(f"{key.replace('_', ' ')} must be between {low:g} and {high:g} {unit}.", field=key)
            clean[key] = round(number, 3)
        return clean

    # ------------------------------------------------------------------ export / delete

    def csv(self, batch_id: str) -> str:
        self._require_batch(batch_id)
        return records_to_csv(self.repo.records_for(batch_id))

    def delete_batch(self, batch_id: str) -> Optional[int]:
        batch = self.repo.get_batch(batch_id)
        if not batch:
            return None
        if batch["status"] in (BATCH_QUEUED, BATCH_RUNNING):
            raise InputError("This batch is still being read. Please wait until it finishes before deleting it.")
        shutil.rmtree(self.settings.cs1_frame_dir / batch_id, ignore_errors=True)
        return self.repo.delete_batch(batch_id)

    def summary(self, batch: dict) -> dict:
        batch_id = batch["_id"]
        counts = self.repo.status_counts(batch_id)
        done = sum(counts.values())
        # "read automatically" ignores reviewer corrections: OK before any review
        auto_ok = self.repo.count(batch_id, status="OK", reviewed=False) + self.repo.count(batch_id, **{"auto.status": "OK"})
        return {"total": batch["total"], "done": done, "counts": counts,
                "reviewed": self.repo.count(batch_id, reviewed=True),
                "ok": counts.get("OK", 0), "flagged": done - counts.get("OK", 0),
                "auto_read_pct": round(100 * auto_ok / done, 1) if done else 0.0}

    def _require_batch(self, batch_id: str) -> dict:
        batch = self.repo.get_batch(batch_id)
        if not batch:
            raise InputError("Batch not found.")
        return batch

