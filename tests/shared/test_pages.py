"""Home page and navigation between the case studies."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    settings = Settings(force_in_memory_db=True, storage_dir=tmp_path)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_home_links_to_every_case_study(client):
    page = client.get("/")
    assert page.status_code == 200
    assert 'href="/case-study-1"' in page.text
    assert 'href="/case-study-2"' in page.text
    assert 'href="/case-study-3"' in page.text


@pytest.mark.parametrize("path, heading", [
    ("/case-study-1", "Case Study 1: Parcel images to shipment data"),
    ("/case-study-2", "Case Study 2: Wagesheet vs PF / ESIC ECR verification"),
    ("/case-study-3", "Case Study 3: Daily FC P&amp;L monitor"),
])
def test_case_study_pages_open(client, path, heading):
    page = client.get(path)
    assert page.status_code == 200
    assert heading in page.text


def test_cs2_job_page_uses_new_path(client):
    page = client.get("/case-study-2/jobs/abc123")
    assert page.status_code == 200
    assert 'data-job-id="abc123"' in page.text


def test_old_job_link_redirects(client):
    response = client.get("/jobs/abc123", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/case-study-2/jobs/abc123"


def test_active_menu_item_is_highlighted(client):
    page = client.get("/case-study-3")
    assert 'href="/case-study-3" class="active"' in page.text
