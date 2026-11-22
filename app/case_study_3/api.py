"""
JSON API for Case Study 3 (all under /api/cs3).

    POST   /runs                         upload a CSV / Excel -> run id (processed in background)
    GET    /runs                         recent runs
    GET    /runs/{id}                    status, progress, summary, warnings
    GET    /runs/{id}/days               computed daily P&L (filter: fc, colour)
    GET    /runs/{id}/anomalies          anomaly log (filter: fc, severity, open_only)
    GET    /runs/{id}/report             Excel download
    DELETE /runs/{id}                    delete an analysis (record, files and the days it stored)
    GET    /digests/preview              HTML digest for one FC (latest day or ?date=)
    POST   /digests/send                 build + deliver digests (all FCs or a list)
    GET    /digests                      delivery log
    GET    /dashboard                    FC x date status grid from history
    GET    /overrides  POST /overrides  DELETE /overrides/{id}   manager "known issue" notes
    GET    /samples/{name}               download the sample / test data files
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT
from app.container import Container, get_container
from app.shared.errors import InputError
from app.case_study_3 import rules
from app.case_study_3.repository import RUN_COMPLETED
from app.case_study_3.service import RunOptions, new_run_id, save_upload

router = APIRouter(prefix="/api/cs3", tags=["case study 3"])

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}
SAMPLE_FILES = {
    "case-study-3-sample.xlsx": "Case Study 3.xlsx",
    "multi-fc-may-2025.csv": "multi_fc_may_2025.csv",
    "fc-managers.csv": "fc_managers.csv",
}


# ---------------------------------------------------------------------- runs

@router.post("/runs", status_code=202)
async def create_run(
    data_file: UploadFile = File(...),
    fc_name: str = Form("FC-01"),
    start_date: str = Form(""),
    send_digests: bool = Form(False),
    container: Container = Depends(get_container),
):
    filename = data_file.filename or ""
    suffix = Path(filename).suffix.lower()
    content = await data_file.read()
    if not filename:
        raise InputError("Please choose a file to upload.", field="data_file")
    if suffix not in ALLOWED_EXTENSIONS:
        raise InputError(f"The file must be .xlsx or .csv (got '{suffix or 'no extension'}').", field="data_file")
    if not content:
        raise InputError("The uploaded file is empty.", field="data_file")
    if len(content) > container.settings.max_upload_mb * 1024 * 1024:
        raise InputError(f"The file is larger than {container.settings.max_upload_mb} MB.", field="data_file")

    run_id = new_run_id()
    path = save_upload(container.settings.upload_dir, run_id, filename, content)
    options = RunOptions(fc_name=fc_name.strip() or "FC-01", start_date=start_date.strip() or None,
                         send_digests=send_digests)
    container.cs3_repo.create_run(run_id, filename, path, options.__dict__)
    container.cs3.submit(run_id, path, options)
    return {"run_id": run_id, "status": "queued"}


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=100), container: Container = Depends(get_container)):
    return [_public_run(r) for r in container.cs3_repo.list_runs(limit)]


@router.get("/runs/{run_id}")
def get_run(run_id: str, container: Container = Depends(get_container)):
    return _public_run(_require_run(run_id, container))


@router.get("/runs/{run_id}/days")
def get_days(run_id: str, fc: Optional[str] = None, colour: Optional[str] = None,
             container: Container = Depends(get_container)):
    _require_run(run_id, container)
    return container.cs3_repo.days_for_run(run_id, fc=fc, colour=colour)


@router.get("/runs/{run_id}/anomalies")
def get_anomalies(run_id: str, fc: Optional[str] = None, severity: Optional[str] = None,
                  open_only: bool = False, container: Container = Depends(get_container)):
    _require_run(run_id, container)
    rows = []
    for day in container.cs3_repo.days_for_run(run_id, fc=fc):
        for anomaly in day["anomalies"]:
            if severity and anomaly["severity"] != severity:
                continue
            if open_only and anomaly["acknowledged"]:
                continue
            rows.append({**anomaly, "colour": day["colour"]})
    return rows


@router.get("/runs/{run_id}/report")
def download_report(run_id: str, container: Container = Depends(get_container)):
    run = _require_run(run_id, container)
    if run["status"] != RUN_COMPLETED or not run.get("report_path") or not Path(run["report_path"]).exists():
        raise HTTPException(409, "The report is not ready.")
    return FileResponse(run["report_path"], filename=f"FC_PnL_report_{run_id}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.delete("/runs/{run_id}")
def delete_run(run_id: str, container: Container = Depends(get_container)):
    removed = container.cs3.delete_run(run_id)
    if removed is None:
        raise HTTPException(404, "No run found with this id.")
    return {"status": "deleted", "days_removed": removed}


# ---------------------------------------------------------------------- digests

class SendRequest(BaseModel):
    fcs: Optional[list[str]] = None
    date: Optional[str] = Field(None, description="YYYY-MM-DD; default = each FC's latest day")


@router.get("/digests/preview", response_class=HTMLResponse)
def preview_digest(fc: str, day: Optional[str] = Query(None, alias="date"),
                   container: Container = Depends(get_container)):
    digest = container.cs3.digest_agent(fc, _parse_date(day))
    if digest is None:
        raise HTTPException(404, f"No data stored for {fc}{' on ' + day if day else ''}.")
    header = (f"<div style='font-family:Arial;font-size:12px;color:#666;margin-bottom:10px'>"
              f"To: {digest.recipient or 'no email configured'} &nbsp;·&nbsp; Subject: {digest.subject}"
              f" &nbsp;·&nbsp; insight: {digest.insight_mode}</div>")
    return HTMLResponse(header + digest.html)


@router.post("/digests/send")
def send_digests(body: SendRequest, container: Container = Depends(get_container)):
    records = container.cs3.send_digests(fcs=set(body.fcs) if body.fcs else None, day=_parse_date(body.date))
    if not records:
        raise HTTPException(404, "There is no stored data to build a digest from. Upload a file first.")
    return {"channel": container.cs3.notifier.channel, "results": records}


@router.get("/digests")
def digest_log(container: Container = Depends(get_container)):
    return [{**r, "created_at": r["created_at"].isoformat()} for r in container.cs3_repo.digests_for()]


# ---------------------------------------------------------------------- dashboard & overrides

@router.get("/dashboard")
def dashboard(days: int = Query(31, ge=1, le=120), container: Container = Depends(get_container)):
    return container.cs3.dashboard(days)


class OverrideRequest(BaseModel):
    fc: str
    line_item: str
    date_from: str
    date_to: str
    note: str = Field("", max_length=200)


@router.get("/overrides")
def list_overrides(container: Container = Depends(get_container)):
    return [{**o, "created_at": o["created_at"].isoformat()} for o in container.cs3_repo.override_documents()]


@router.post("/overrides", status_code=201)
def add_override(body: OverrideRequest, container: Container = Depends(get_container)):
    if body.line_item not in rules.COST_LINES + ["CM1 %", "CM2 %"]:
        raise InputError(f"Unknown line item '{body.line_item}'.")
    start, end = _parse_date(body.date_from), _parse_date(body.date_to)
    if not start or not end:
        raise InputError("Dates must be in YYYY-MM-DD format.")
    container.cs3.add_override(body.fc, body.line_item, start, end, body.note)
    return {"status": "saved", "applies_to": "runs processed from now on"}


@router.delete("/overrides/{override_id}")
def delete_override(override_id: str, container: Container = Depends(get_container)):
    if not container.cs3_repo.delete_override(override_id):
        raise HTTPException(404, "Known issue not found.")
    return {"status": "deleted"}


@router.get("/samples/{name}")
def download_sample(name: str):
    if name not in SAMPLE_FILES:
        raise HTTPException(404, "Unknown sample file.")
    return FileResponse(PROJECT_ROOT / "data" / "case_study_3" / SAMPLE_FILES[name], filename=name)


# ---------------------------------------------------------------------- helpers

def _require_run(run_id: str, container: Container) -> dict:
    run = container.cs3_repo.get_run(run_id)
    if not run:
        raise HTTPException(404, "No run found with this id.")
    return run


def _public_run(run: dict) -> dict:
    public = {k: v for k, v in run.items() if k not in {"stored_path", "report_path"}}
    public["run_id"] = public.pop("_id")
    for key in ("created_at", "updated_at"):
        if public.get(key):
            public[key] = public[key].isoformat()
    return public


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InputError(f"'{value}' is not a valid date (use YYYY-MM-DD).")
