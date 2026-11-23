"""
Case Study 1 pages. Data is loaded by each page's JavaScript from the JSON API (api.py).

    /case-study-1                          upload page + recent batches
    /case-study-1/batches/{batch_id}       results of one batch (progress, counts, grid, table, CSV)
    /case-study-1/batches/{batch_id}/review  flagged frames one by one: confirm, correct or keep the flag
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.container import Container, get_container
from app.shared.pages import render

BASE_PATH = "/case-study-1"
router = APIRouter(include_in_schema=False)


@router.get(BASE_PATH, response_class=HTMLResponse)
def upload_page(request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_1/index.html", container, active="cs1", mode=container.cs1.mode)


@router.get(BASE_PATH + "/batches/{batch_id}", response_class=HTMLResponse)
def batch_page(batch_id: str, request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_1/batch.html", container, active="cs1", batch_id=batch_id)


@router.get(BASE_PATH + "/batches/{batch_id}/review", response_class=HTMLResponse)
def review_page(batch_id: str, request: Request, container: Container = Depends(get_container)):
    return render(request, "case_study_1/review.html", container, active="cs1", batch_id=batch_id)
