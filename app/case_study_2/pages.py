"""
Case Study 2 pages. Data is loaded by each page's JavaScript from the JSON API (api.py).

    /case-study-2                   upload page (wagesheet + PF ECR + ESIC ECR)
    /case-study-2/jobs/{job_id}     results of one verification job
    /jobs/{job_id}                  old address, redirected so earlier bookmarks keep working
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.container import Container, get_container
from app.shared.pages import render

BASE_PATH = "/case-study-2"
router = APIRouter(include_in_schema=False)


@router.get(BASE_PATH, response_class=HTMLResponse)
def upload_page(request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_2/index.html", container, active="cs2")


@router.get(BASE_PATH + "/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str, request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_2/job.html", container, active="cs2", job_id=job_id)


@router.get("/jobs/{job_id}")
def legacy_job_redirect(job_id: str):
    return RedirectResponse(f"{BASE_PATH}/jobs/{job_id}", status_code=307)
