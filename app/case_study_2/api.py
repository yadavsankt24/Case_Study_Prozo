"""
Case Study 2 JSON API: verification jobs and the Ask assistant.

    POST /api/jobs                      upload 3 files -> job id (processing starts in background)
    GET  /api/jobs                      recent jobs
    GET  /api/jobs/{job_id}             status, progress, summary, warnings
    GET  /api/jobs/{job_id}/results     employee verdicts (filter, search, paginate)
    GET  /api/jobs/{job_id}/ecr-only    ECR members not on the wagesheet
    GET  /api/jobs/{job_id}/report      download the Excel report
    POST /api/jobs/{job_id}/ask         question about the results or PF/ESIC rules
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.container import Container, get_container
from app.case_study_2.validation import check_upload
from app.case_study_2.repository import JobStatus
from app.case_study_2.job_runner import save_upload

router = APIRouter(prefix="/api/jobs", tags=["case study 2"])


@router.post("", status_code=202)
async def create_job(
    wagesheet: UploadFile = File(...),
    pf_ecr: UploadFile = File(...),
    esic_ecr: UploadFile = File(...),
    label: str = Form(""),
    container: Container = Depends(get_container),
):
    uploads = {"wagesheet": wagesheet, "pf_ecr": pf_ecr, "esic_ecr": esic_ecr}
    contents: dict[str, bytes] = {}
    for slot, upload in uploads.items():
        contents[slot] = await upload.read()
        # Raises InputError -> 400 with a friendly message (see main.py handler)
        check_upload(slot, upload.filename or "", len(contents[slot]), container.settings.max_upload_mb)

    job_id = uuid.uuid4().hex[:12]
    stored_paths = {
        slot: save_upload(container.settings.upload_dir, job_id, slot, uploads[slot].filename, data)
        for slot, data in contents.items()
    }
    input_files = {slot: upload.filename for slot, upload in uploads.items()}
    container.jobs.create(job_id, label.strip(), input_files, stored_paths)
    container.runner.submit(job_id, stored_paths)
    return {"job_id": job_id, "status": JobStatus.QUEUED.value}


@router.get("")
def list_jobs(limit: int = Query(20, ge=1, le=100), container: Container = Depends(get_container)):
    return [_public_job(job) for job in container.jobs.list_recent(limit)]


@router.get("/{job_id}")
def get_job(job_id: str, container: Container = Depends(get_container)):
    return _public_job(_require_job(job_id, container))


@router.get("/{job_id}/results")
def get_results(
    job_id: str,
    check: Optional[str] = Query(None, pattern="^(pf|esic)$"),
    status: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=100),
    needs_review: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    container: Container = Depends(get_container),
):
    _require_job(job_id, container)
    items, total = container.results.find_employees(
        job_id, check=check, status=status, search=q, needs_review=needs_review,
        skip=(page - 1) * page_size, limit=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{job_id}/ecr-only")
def get_ecr_only(job_id: str, container: Container = Depends(get_container)):
    _require_job(job_id, container)
    return container.results.find_ecr_only(job_id)


@router.get("/{job_id}/report")
def download_report(job_id: str, container: Container = Depends(get_container)):
    job = _require_job(job_id, container)
    if job["status"] != JobStatus.COMPLETED.value or not job.get("report_path"):
        raise HTTPException(409, "The report is not ready yet.")
    path = Path(job["report_path"])
    if not path.exists():
        raise HTTPException(410, "The report file is no longer available. Please run the verification again.")
    name = f"PF_ESIC_verification_{job.get('label') or job_id}.xlsx".replace(" ", "_")
    return FileResponse(path, filename=name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------------- Ask assistant

class Question(BaseModel):
    question: str = Field(..., max_length=500)


@router.post("/{job_id}/ask")
def ask(job_id: str, body: Question, container: Container = Depends(get_container)):
    _require_job(job_id, container)
    return asdict(container.assistant.ask(job_id, body.question))


# ---------------------------------------------------------------------- #

def _require_job(job_id: str, container: Container) -> dict:
    job = container.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No verification job found with this id.")
    return job


def _public_job(job: dict) -> dict:
    """Shape a job document for the API (hide internal file paths)."""
    hidden = {"stored_paths", "report_path"}
    public = {k: v for k, v in job.items() if k not in hidden}
    public["job_id"] = public.pop("_id")
    public["report_ready"] = job.get("status") == JobStatus.COMPLETED.value
    for key in ("created_at", "updated_at"):
        if public.get(key):
            public[key] = public[key].isoformat()
    return public

