"""The Gemini client: request, retries and answer parsing (HTTP is faked; no network in tests)."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from app.case_study_1 import vision as vision_module
from app.case_study_1.vision import GeminiVision, parse_response, result_from_json

ANSWER = {"parcel_count": 1, "parcel_cut_off": True, "view_obstructed": False, "person_in_frame": False,
          "label_count": 1, "overlay_present": True, "overlay_awb": "19108610817924",
          "overlay_dimensions_text": "L0213XH0148XW0178", "overlay_weight_text": "01190",
          "label_awb": None, "image_quality": "dark", "notes": "Frame is split; lower half captured."}


class FakeResponse:
    def __init__(self, status: int, body=None):
        self.status_code, self._body = status, body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def gemini_body(answer: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True},
                                                  {"text": "```json\n" + json.dumps(answer) + "\n```"}]}}]}


@pytest.fixture()
def frame():
    return Image.new("RGB", (800, 500), (30, 30, 30))


def test_parse_answer():
    result = parse_response(gemini_body(ANSWER), "gemini-test")
    assert result.parcel_cut_off and result.overlay_awb == "19108610817924" and result.label_awb is None
    assert result.model == "gemini-test"
    with pytest.raises(ValueError):
        result_from_json("not json")
    with pytest.raises(ValueError):
        result_from_json(json.dumps({"something": 1}))


def test_request_and_retry(monkeypatch, frame):
    calls = []

    def fake_post(url, params, json, timeout):
        calls.append(json)
        return FakeResponse(429) if len(calls) == 1 else FakeResponse(200, gemini_body(ANSWER))

    monkeypatch.setattr(vision_module.requests, "post", fake_post)
    reader = GeminiVision("key", "gemini-test", per_minute=6000, sleep=lambda s: None)
    result, error = reader.read(frame)
    assert error is None and result.parcel_count == 1 and len(calls) == 2
    parts = calls[0]["contents"][0]["parts"]
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert calls[0]["generationConfig"]["responseMimeType"] == "application/json"


def test_unknown_model_gives_a_clear_message(monkeypatch, frame):
    monkeypatch.setattr(vision_module.requests, "post", lambda *a, **k: FakeResponse(404, {"error": "not found"}))
    result, error = GeminiVision("key", "gemini-old", sleep=lambda s: None).read(frame)
    assert result is None and "CS1_VISION_MODEL" in error


def test_schema_rejected_falls_back_to_plain_json(monkeypatch, frame):
    calls = []

    def fake_post(url, params, json, timeout):
        calls.append("responseSchema" in json["generationConfig"])
        if calls[-1]:
            return FakeResponse(400, {"error": {"message": "Invalid responseSchema"}})
        return FakeResponse(200, gemini_body(ANSWER))

    monkeypatch.setattr(vision_module.requests, "post", fake_post)
    result, error = GeminiVision("key", "m", per_minute=6000, sleep=lambda s: None).read(frame)
    assert error is None and calls == [True, False]


def test_gives_up_after_retries(monkeypatch, frame):
    monkeypatch.setattr(vision_module.requests, "post", lambda *a, **k: FakeResponse(503))
    result, error = GeminiVision("key", "m", per_minute=6000, sleep=lambda s: None).read(frame)
    assert result is None and "after 4 attempts" in error
