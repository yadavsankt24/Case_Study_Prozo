"""Case Study 1 end to end through the API (in-memory MongoDB, offline readers)."""

from __future__ import annotations

import csv
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import CS1_SAMPLE


@pytest.fixture()
def client(tmp_path):
    settings = Settings(force_in_memory_db=True, storage_dir=tmp_path, gemini_api_key="")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def sample_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(CS1_SAMPLE.glob("*")):
            if path.suffix != ".csv":
                archive.write(path, f"frames/{path.name}")
        archive.writestr("__MACOSX/._junk.png", b"junk")
        archive.writestr("frames/readme.txt", b"not an image")
    return buffer.getvalue()


def wait(client, batch_id):
    for _ in range(300):
        batch = client.get(f"/api/cs1/batches/{batch_id}").json()
        if batch["status"] in ("completed", "failed"):
            return batch
        time.sleep(0.1)
    raise AssertionError("batch did not finish")


def upload(client, files, label=""):
    response = client.post("/api/cs1/batches", files=files, data={"label": label})
    assert response.status_code == 202, response.text
    return response.json()


def test_zip_batch_to_csv_review_and_delete(client):
    created = upload(client, [("files", ("frames.zip", sample_zip()))], label="sample")
    assert created["frames"] == 5 and created["skipped"] == ["frames.zip/frames/readme.txt"]
    batch = wait(client, created["batch_id"])
    assert batch["status"] == "completed" and batch["vision_enabled"] is False
    assert batch["summary"]["counts"] == {"OK": 5} and batch["summary"]["auto_read_pct"] == 100.0

    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/cs1/batches/{created['batch_id']}/csv").text)))
    assert len(rows) == 5
    assert rows[2]["image_file"] == "Half shipment captured.png"                 # dataset suffix removed
    assert rows[2]["awb"] == "19108610817924" and rows[2]["weight_kg"] == "1.19"
    assert rows[4]["confidence"] == "high"                                        # barcode confirmed

    record_id = client.get(f"/api/cs1/batches/{created['batch_id']}/records").json()[2]["record_id"]
    detail = client.get(f"/api/cs1/records/{record_id}").json()
    assert detail["readers"]["ocr"]["rows"] and "stored_path" not in detail
    assert client.get(f"/api/cs1/records/{record_id}/thumbnail").headers["content-type"] == "image/jpeg"

    bad = client.patch(f"/api/cs1/records/{record_id}", json={"action": "confirm", "awb": "12"})
    assert bad.status_code == 400 and "valid AWB" in bad.json()["detail"]
    reviewed = client.patch(f"/api/cs1/records/{record_id}", json={
        "action": "keep_flag", "note": "half frame, re-scan"}).json()
    assert reviewed["reviewed"] and "reviewer: half frame, re-scan" in reviewed["notes"]
    assert reviewed["auto"]["status"] == "OK"

    assert client.delete(f"/api/cs1/batches/{created['batch_id']}").json()["records_removed"] == 5
    assert client.get(f"/api/cs1/batches/{created['batch_id']}").status_code == 404


def test_confirm_with_corrections(client):
    name = "Half shipment captured_png.rf.WNrelVB6aeQO3rpN0eiY.png"
    created = upload(client, [("files", (name, (CS1_SAMPLE / name).read_bytes()))])
    wait(client, created["batch_id"])
    record_id = client.get(f"/api/cs1/batches/{created['batch_id']}/records").json()[0]["record_id"]
    out = client.patch(f"/api/cs1/records/{record_id}", json={
        "action": "confirm", "awb": "19108610817924", "length_cm": 21.3, "width_cm": 17.8,
        "height_cm": 14.8, "weight_kg": 300}).json()
    assert "between" in out["detail"]                                            # 300 kg rejected
    out = client.patch(f"/api/cs1/records/{record_id}", json={
        "action": "confirm", "awb": "19108610817924", "length_cm": 21.3, "width_cm": 17.8,
        "height_cm": 14.8, "weight_kg": 1.19}).json()
    assert out["status"] == "OK" and out["reviewed"] and out["status_reason"] == "Confirmed by a reviewer."


def test_broken_files_get_a_row(client, cs1_generated):
    files = [("files", (n, (cs1_generated / n).read_bytes())) for n in ("40_corrupt_file.jpg", "41_tiny_image.jpg")]
    created = upload(client, files)
    batch = wait(client, created["batch_id"])
    assert batch["summary"]["counts"] == {"INVALID_IMAGE": 2}


@pytest.mark.parametrize("files, message", [
    ([("files", ("notes.txt", b"hello"))], "No images found"),
    ([("files", ("frames.zip", b"not a zip"))], "not a valid ZIP"),
])
def test_bad_uploads(client, files, message):
    response = client.post("/api/cs1/batches", files=files)
    assert response.status_code == 400 and message in response.json()["detail"]


def test_sample_zip_download(client):
    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/cs1/samples/sample-frames.zip").content))
    assert len(archive.namelist()) == 5


def test_pages(client):
    assert "Offline mode" in client.get("/case-study-1").text
    assert 'data-batch-id="abc"' in client.get("/case-study-1/batches/abc").text
    assert "Review flagged frames" in client.get("/case-study-1/batches/abc/review").text


def test_database_outage_gives_a_clear_503(client, monkeypatch):
    from pymongo.errors import AutoReconnect

    def broken(*args, **kwargs):
        raise AutoReconnect("SSL handshake failed: [SSL: BAD_PSK_IDENTITY] bad message type")

    monkeypatch.setattr(client.app.state.container.cs1_repo, "get_batch", broken)
    response = client.get("/api/cs1/batches/abc")
    assert response.status_code == 503 and "try again" in response.json()["detail"]


def test_saving_a_result_survives_a_temporary_database_error(client, monkeypatch):
    from pymongo.errors import AutoReconnect
    from app.case_study_1 import service as service_module

    monkeypatch.setattr(service_module.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise AutoReconnect("connection reset")
        return "saved"

    assert service_module.Cs1Service._with_retry(flaky) == "saved" and calls["n"] == 3
