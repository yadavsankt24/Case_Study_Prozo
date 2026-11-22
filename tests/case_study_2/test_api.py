"""API flow with an in-memory MongoDB (mongomock): upload -> background job -> results -> report -> ask."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import SAMPLE_ESIC, SAMPLE_PF, SAMPLE_WAGESHEET


@pytest.fixture()
def client(tmp_path):
    settings = Settings(force_in_memory_db=True, storage_dir=tmp_path)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _upload(client, pf=SAMPLE_PF):
    with open(SAMPLE_WAGESHEET, "rb") as w, open(pf, "rb") as p, open(SAMPLE_ESIC, "rb") as e:
        response = client.post("/api/jobs", data={"label": "test"},
                               files={"wagesheet": w, "pf_ecr": p, "esic_ecr": e})
    assert response.status_code == 202
    return response.json()["job_id"]


def _wait(client, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_full_flow(client):
    job_id = _upload(client)
    job = _wait(client, job_id)
    assert job["status"] == "completed"
    assert job["summary"]["pf"]["counts"]["Matched"] == 9

    results = client.get(f"/api/jobs/{job_id}/results", params={"check": "esic", "status": "Missing"}).json()
    assert {r["name"] for r in results["items"]} == {"SANJAY PASWAN", "POOJA GUPTA"}

    report = client.get(f"/api/jobs/{job_id}/report")
    assert report.status_code == 200 and report.content[:2] == b"PK"   # xlsx is a zip

    answer = client.post(f"/api/jobs/{job_id}/ask", json={"question": "Why is Vikram flagged?"}).json()
    assert answer["intent"] == "employee_lookup" and "300" in answer["answer"]


def test_failed_job_shows_clear_message(client):
    job_id = _upload(client, pf=SAMPLE_ESIC)   # ESIC file placed in the PF box
    job = _wait(client, job_id)
    assert job["status"] == "failed"
    assert "looks like an ESIC ECR" in job["error"]


def test_bad_upload_is_rejected_immediately(client):
    response = client.post("/api/jobs", files={"wagesheet": ("w.txt", b"x"), "pf_ecr": ("p.pdf", b"x"),
                                               "esic_ecr": ("e.pdf", b"x")})
    assert response.status_code == 400
    assert "must be one of" in response.json()["detail"]


def test_unknown_job_returns_404(client):
    assert client.get("/api/jobs/doesnotexist").status_code == 404


def test_nonsense_question_gets_guidance(client):
    job_id = _upload(client)
    _wait(client, job_id)
    answer = client.post(f"/api/jobs/{job_id}/ask", json={"question": "zzqx blorp"}).json()
    assert answer["intent"] in ("off_topic", "invalid")
