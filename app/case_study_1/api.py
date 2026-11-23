"""
JSON API for Case Study 1 (all under /api/cs1).

    POST   /batches                      upload frames and / or ZIPs -> batch id (read in background)
    GET    /batches                      recent batches
    GET    /batches/{id}                 status, progress, counts per status
    GET    /batches/{id}/records         one record per frame (filter: status, flagged)
    GET    /batches/{id}/csv             CSV download, one row per frame
    POST   /batches/{id}/rerun           re-read every PROCESSING_ERROR frame
    DELETE /batches/{id}                 delete a batch, its frames and records
    GET    /records/{id}                 one record with every reader's output
    PATCH  /records/{id}                 review: confirm (with corrections) or keep the flag
    POST   /records/{id}/rerun           re-read one frame
    GET    /records/{id}/image           the original frame
    GET    /records/{id}/thumbnail       small JPEG for the grid
    GET    /samples/sample-frames.zip    the 5 sample frames as one ZIP
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.case_study_1.repository import STATE_DONE
from app.config import PROJECT_ROOT
from app.container import Container, get_container
from app.shared.errors import InputError

router = APIRouter(prefix="/api/cs1", tags=["case study 1"])

SAMPLE_DIR = PROJECT_ROOT / "data" / "case_study_1" / "sample"
HIDDEN_FIELDS = {"stored_path", "thumb_path"}


# ---------------------------------------------------------------------- batches

@router.post("/batches", status_code=202)
async def create_batch(files: list[UploadFile] = File(...), label: str = Form(""),
                       container: Container = Depends(get_container)):
    uploads, total_bytes = [], 0
    for upload in files:
        content = await upload.read()
        total_bytes += len(content)
        if upload.filename and content:
            uploads.append((upload.filename, content))
    if not uploads:
        raise InputError("Please choose at least one image or ZIP file.", field="files")
    if total_bytes > container.settings.cs1_max_upload_mb * 1024 * 1024:
        raise InputError(f"The upload is larger than {container.settings.cs1_max_upload_mb} MB. "
                         "Split it into smaller batches.", field="files")
    return container.cs1.create_batch(uploads, label)


@router.get("/batches")
def list_batches(limit: int = Query(20, ge=1, le=100), container: Container = Depends(get_container)):
    return [_public_batch(b, container) for b in container.cs1_repo.list_batches(limit)]


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, container: Container = Depends(get_container)):
    return _public_batch(_require_batch(batch_id, container), container)


@router.get("/batches/{batch_id}/records")
def get_records(batch_id: str, status: Optional[str] = None, flagged: bool = False,
                container: Container = Depends(get_container)):
    _require_batch(batch_id, container)
    return [_public_record(r) for r in container.cs1_repo.records_for(batch_id, status=status, flagged_only=flagged)]


@router.get("/batches/{batch_id}/csv")
def download_csv(batch_id: str, container: Container = Depends(get_container)):
    _require_batch(batch_id, container)
    return Response(container.cs1.csv(batch_id), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="shipments_{batch_id}.csv"'})


@router.post("/batches/{batch_id}/rerun")
def rerun_failed(batch_id: str, container: Container = Depends(get_container)):
    return {"requeued": container.cs1.rerun(batch_id)}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str, container: Container = Depends(get_container)):
    removed = container.cs1.delete_batch(batch_id)
    if removed is None:
        raise HTTPException(404, "Batch not found.")
    return {"status": "deleted", "records_removed": removed}


# ---------------------------------------------------------------------- records

class ReviewRequest(BaseModel):
    action: str = Field(..., description="confirm | keep_flag")
    awb: Optional[str] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    note: str = ""


@router.get("/records/{record_id}")
def get_record(record_id: str, container: Container = Depends(get_container)):
    return _public_record(_require_record(record_id, container), detail=True)


@router.patch("/records/{record_id}")
def review_record(record_id: str, body: ReviewRequest, container: Container = Depends(get_container)):
    _require_record(record_id, container)
    values = body.model_dump(exclude={"action", "note"})
    return _public_record(container.cs1.review_record(record_id, body.action, values, body.note), detail=True)


@router.post("/records/{record_id}/rerun")
def rerun_record(record_id: str, container: Container = Depends(get_container)):
    record = _require_record(record_id, container)
    return {"requeued": container.cs1.rerun(record["batch_id"], record_id)}


@router.get("/records/{record_id}/image")
def record_image(record_id: str, container: Container = Depends(get_container)):
    return _file(_require_record(record_id, container).get("stored_path"))


@router.get("/records/{record_id}/thumbnail")
def record_thumbnail(record_id: str, container: Container = Depends(get_container)):
    record = _require_record(record_id, container)
    return _file(record.get("thumb_path") or record.get("stored_path"))


# ---------------------------------------------------------------------- samples

@router.get("/samples/sample-frames.zip")
def sample_frames():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SAMPLE_DIR.glob("*")):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                archive.write(path, path.name)
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="case_study_1_sample_frames.zip"'})


# ---------------------------------------------------------------------- helpers

def _require_batch(batch_id: str, container: Container) -> dict:
    batch = container.cs1_repo.get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found.")
    return batch


def _require_record(record_id: str, container: Container) -> dict:
    record = container.cs1_repo.get_record(record_id)
    if not record:
        raise HTTPException(404, "Frame not found.")
    return record


def _file(path: Optional[str]) -> FileResponse:
    if not path or not Path(path).exists():
        raise HTTPException(404, "Image not found.")
    return FileResponse(path)


def _public_batch(batch: dict, container: Container) -> dict:
    data = {k: v for k, v in batch.items() if k != "_id"}
    data["batch_id"] = batch["_id"]
    data["summary"] = container.cs1.summary(batch)
    return data


def _public_record(record: dict, detail: bool = False) -> dict:
    data = {k: v for k, v in record.items() if k not in HIDDEN_FIELDS and k != "_id"}
    data["record_id"] = record["_id"]
    data["done"] = record.get("state") == STATE_DONE
    if not detail:
        data.pop("readers", None)
    return data
