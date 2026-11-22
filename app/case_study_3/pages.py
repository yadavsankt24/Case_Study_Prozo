"""
Case Study 3 pages. Data is loaded by each page's JavaScript from the JSON API (api.py).

    /case-study-3                   upload page + recent analyses
    /case-study-3/runs/{run_id}     results of one upload
    /case-study-3/dashboard         central dashboard across all FCs (from history)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.container import Container, get_container
from app.shared.pages import render

BASE_PATH = "/case-study-3"
router = APIRouter(include_in_schema=False)


@router.get(BASE_PATH, response_class=HTMLResponse)
def upload_page(request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_3/index.html", container, active="cs3")


@router.get(BASE_PATH + "/runs/{run_id}", response_class=HTMLResponse)
def run_page(run_id: str, request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_3/run.html", container, active="cs3", run_id=run_id)


@router.get(BASE_PATH + "/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_3/dashboard.html", container, active="cs3",
                  delivery="email" if container.settings.smtp_configured else "outbox")
