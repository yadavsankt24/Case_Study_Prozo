"""
Shared page helpers and the home page.

Each case study has its own `pages.py` with its routes; they all render through
`render()` here so every page gets the same base values (active menu item,
demo-mode banner, asset version).

    /        home page with one card per case study
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.container import Container, get_container

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
router = APIRouter(include_in_schema=False)


def asset_version() -> int:
    """
    Latest modification time of the CSS/JS files. Added to their URLs (style.css?v=...)
    so browsers fetch the new file after every change instead of a stale cached copy.
    """
    return int(max(f.stat().st_mtime for f in (APP_DIR / "static").rglob("*") if f.is_file()))


def render(request: Request, template: str, container: Container, active: str, **context) -> HTMLResponse:
    """Render a page with the values every page needs (active menu item, demo-mode banner, asset version)."""
    return templates.TemplateResponse(
        request, template,
        {"active": active, "in_memory_db": container.in_memory_db, "asset_version": asset_version(), **context},
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request, container: Container = Depends(get_container)):
    return render(request, "shared/home.html", container, active="home")
