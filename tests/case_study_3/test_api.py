"""Case Study 3 end to end through the API (in-memory MongoDB, outbox delivery)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import CS3_DATA as CS3


@pytest.fixture()
def client(tmp_path):
    settings = Settings(force_in_memory_db=True, storage_dir=tmp_path)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _run(client, name, **form):
    with open(CS3 / name, "rb") as handle:
        response = client.post("/api/cs3/runs", files={"data_file": (name, handle)}, data=form)
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    for _ in range(100):
        run = client.get(f"/api/cs3/runs/{run_id}").json()
        if run["status"] in ("completed", "failed"):
            return run_id, run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_multi_fc_run_with_digests(client):
    run_id, run = _run(client, "multi_fc_may_2025.csv", send_digests="true")
    assert run["status"] == "completed"
    assert run["summary"]["colours"] == {"Red": 12, "Yellow": 8, "Green": 100, "Blue": 4}
    assert {d["status"] for d in run["summary"]["digests"]} == {"saved"}          # outbox without SMTP

    anomalies = client.get(f"/api/cs3/runs/{run_id}/anomalies", params={"severity": "high"}).json()
    assert anomalies and all(a["line_item"] == "CM2 %" for a in anomalies)
    assert client.get(f"/api/cs3/runs/{run_id}/report").content[:2] == b"PK"


def test_digest_uses_memory_for_trend(client):
    _run(client, "multi_fc_may_2025.csv")
    preview = client.get("/api/cs3/digests/preview", params={"fc": "FC-Kolkata", "date": "2025-05-29"})
    assert preview.status_code == 200
    assert "[RED] FC-Kolkata" in preview.text and "3 Red days in a row" in preview.text


def test_dashboard_shows_every_fc(client):
    _run(client, "multi_fc_may_2025.csv")
    _run(client, "Case Study 3.xlsx", fc_name="FC-01")
    dashboard = client.get("/api/cs3/dashboard").json()
    assert dashboard["fcs"] == ["FC-01", "FC-Bengaluru", "FC-Bhiwandi", "FC-Gurgaon", "FC-Kolkata"]


def test_override_is_applied_to_later_runs(client):
    client.post("/api/cs3/overrides", json={"fc": "FC-Bengaluru", "line_item": "FC Rent",
                                            "date_from": "2025-05-15", "date_to": "2025-05-15", "note": "rent late"})
    run_id, _ = _run(client, "multi_fc_may_2025.csv")
    day = next(d for d in client.get(f"/api/cs3/runs/{run_id}/days", params={"fc": "FC-Bengaluru"}).json()
               if d["date"] == "2025-05-15")
    rent = next(a for a in day["anomalies"] if a["line_item"] == "FC Rent")
    assert rent["acknowledged"] and "rent late" in rent["note"]


def test_bad_upload_and_bad_file(client):
    response = client.post("/api/cs3/runs", files={"data_file": ("x.txt", b"abc")})
    assert response.status_code == 400 and ".xlsx or .csv" in response.json()["detail"]
    _, run = _run(client, "bad_inputs/missing_overheads_column.csv")
    assert run["status"] == "failed" and "Overheads" in run["error"]


def test_pages(client):
    run_id, _ = _run(client, "Case Study 3.xlsx")
    for path in ("/case-study-3", f"/case-study-3/runs/{run_id}", "/case-study-3/dashboard"):
        assert client.get(path).status_code == 200


def test_delete_run_removes_record_files_and_its_days(client):
    run_id, _ = _run(client, "Case Study 3.xlsx", fc_name="FC-01")
    keep_id, _ = _run(client, "multi_fc_may_2025.csv")

    response = client.delete(f"/api/cs3/runs/{run_id}")
    assert response.status_code == 200 and response.json()["days_removed"] == 100

    assert client.get(f"/api/cs3/runs/{run_id}").status_code == 404
    assert run_id not in {r["run_id"] for r in client.get("/api/cs3/runs").json()}
    assert "FC-01" not in client.get("/api/cs3/dashboard").json()["fcs"]          # its days are gone
    assert client.get(f"/api/cs3/runs/{keep_id}").json()["status"] == "completed"  # other runs untouched
    assert client.delete(f"/api/cs3/runs/{run_id}").status_code == 404


def test_delete_keeps_days_replaced_by_a_later_upload(client):
    first_id, _ = _run(client, "multi_fc_may_2025.csv")
    _run(client, "multi_fc_may_2025.csv")                                            # same FC-days again
    assert client.delete(f"/api/cs3/runs/{first_id}").json()["days_removed"] == 0
    assert len(client.get("/api/cs3/dashboard").json()["fcs"]) == 4
