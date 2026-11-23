"""
Vision agent: one Gemini call per frame.

It does the part offline readers cannot: judge the scene (how many parcels, cut off by
the frame, something covering it). It also gives an independent second read of the
overlay and of the label's tracking number, which is compared with the OCR read.

Rules given to the model: JSON only, copy text exactly as printed, null instead of a
guess, ignore names / addresses / phone numbers.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
from typing import Optional, Protocol

import requests
from PIL import Image

from app.case_study_1 import rules
from app.case_study_1.models import VisionResult

log = logging.getLogger(__name__)

PROMPT = """You are checking one camera frame from a parcel scanning / sorting machine in a warehouse.
The machine usually prints its readings as a text overlay on the frame (AWB / barcode number,
dimensions, weight, time, location). The parcel may also carry a courier shipping label.

Answer ONLY with JSON matching the schema. Rules:
- parcel_count: number of parcels (boxes, envelopes, pouches) visible, even partly. 0 if none.
- parcel_cut_off: true if the parcel is not fully inside the frame or the frame is split / half captured.
- view_obstructed: true if a hand, person, tool or object covers part of the parcel or its label.
- person_in_frame: true if a person or body part is visible anywhere.
- label_count: number of shipping labels visible on the parcel.
- overlay_present: true if machine readings are printed on the frame as text.
- overlay_awb: the AWB / barcode / tracking number in the overlay, digits exactly as printed, else null.
- overlay_dimensions_text: the dimensions exactly as printed in the overlay, including key letters and units
  (for example "L: 39 cm, W: 28.5 cm, H: 29 cm" or "0208 X 0148 X 0163"), else null.
- overlay_weight_text: the actual weight exactly as printed with its unit if any (not volumetric weight), else null.
- label_awb: the tracking / AWB number printed on the shipping label, only if every character is clearly readable, else null.
- image_quality: one of good, blurred, dark, glare.
- notes: at most one short sentence about anything unusual.
Never guess or complete a partly hidden number: use null. Ignore names, addresses and phone numbers."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "parcel_count": {"type": "INTEGER"},
        "parcel_cut_off": {"type": "BOOLEAN"},
        "view_obstructed": {"type": "BOOLEAN"},
        "person_in_frame": {"type": "BOOLEAN"},
        "label_count": {"type": "INTEGER"},
        "overlay_present": {"type": "BOOLEAN"},
        "overlay_awb": {"type": "STRING", "nullable": True},
        "overlay_dimensions_text": {"type": "STRING", "nullable": True},
        "overlay_weight_text": {"type": "STRING", "nullable": True},
        "label_awb": {"type": "STRING", "nullable": True},
        "image_quality": {"type": "STRING", "enum": ["good", "blurred", "dark", "glare"]},
        "notes": {"type": "STRING"},
    },
    "required": ["parcel_count", "parcel_cut_off", "view_obstructed", "person_in_frame", "label_count",
                 "overlay_present", "overlay_awb", "overlay_dimensions_text", "overlay_weight_text",
                 "label_awb", "image_quality", "notes"],
}

TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 4
RETRY_STATUS = {429, 500, 502, 503, 504}


class VisionReader(Protocol):
    name: str

    def read(self, image: Image.Image) -> tuple[Optional[VisionResult], Optional[str]]:
        """(result, error). Exactly one of the two is set."""


class RateLimiter:
    """At most `per_minute` calls per minute across all worker threads."""

    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(per_minute, 1)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if delay:
            time.sleep(delay)


class GeminiVision:
    name = "gemini"

    def __init__(self, api_key: str, model: str, per_minute: int = 10, sleep=time.sleep):
        self.api_key, self.model = api_key, model
        self.limiter = RateLimiter(per_minute)
        self._sleep = sleep
        self._use_schema = True

    def read(self, image: Image.Image) -> tuple[Optional[VisionResult], Optional[str]]:
        payload = _image_part(image)
        last_error = "no response"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.limiter.wait()
            try:
                response = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    params={"key": self.api_key}, json=self._body(payload), timeout=TIMEOUT_SECONDS)
            except requests.RequestException as exc:
                last_error = f"network error: {exc.__class__.__name__}"
            else:
                if response.status_code == 200:
                    try:
                        return parse_response(response.json(), self.model), None
                    except ValueError as exc:
                        last_error = f"unexpected answer from Gemini ({exc})"
                elif response.status_code == 400 and self._use_schema and "schema" in response.text.lower():
                    self._use_schema = False          # older/newer model without schema support: retry plain JSON
                    continue
                elif response.status_code == 404:
                    return None, (f"Gemini model '{self.model}' is not available. "
                                  "Set CS1_VISION_MODEL in .env to a current model (see Google AI Studio).")
                elif response.status_code in RETRY_STATUS:
                    last_error = f"Gemini returned {response.status_code} (rate limit or busy)"
                else:
                    return None, f"Gemini returned {response.status_code}: {_short(response.text)}"
            if attempt < MAX_ATTEMPTS:
                self._sleep(2 ** attempt)
        return None, f"{last_error} after {MAX_ATTEMPTS} attempts"

    def _body(self, image_part: dict) -> dict:
        config = {"temperature": 0, "maxOutputTokens": 2048, "responseMimeType": "application/json"}
        if self._use_schema:
            config["responseSchema"] = RESPONSE_SCHEMA
        return {"contents": [{"parts": [{"text": PROMPT}, image_part]}], "generationConfig": config}


def _image_part(image: Image.Image) -> dict:
    copy = image.convert("RGB")
    copy.thumbnail((rules.VISION_MAX_SIDE_PX, rules.VISION_MAX_SIDE_PX))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=90)
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buffer.getvalue()).decode()}}


def _short(text: str, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", text)[:limit]


def parse_response(body: dict, model: str = "") -> VisionResult:
    """Gemini's HTTP response -> VisionResult. Raises ValueError when the answer is not usable."""
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("no content")
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return result_from_json(text, model)


def result_from_json(text: str, model: str = "") -> VisionResult:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("not JSON")
    if not isinstance(data, dict) or "parcel_count" not in data:
        raise ValueError("missing fields")

    def text_or_none(key: str) -> Optional[str]:
        value = data.get(key)
        value = str(value).strip() if value is not None else ""
        return value if value and value.lower() not in {"null", "none", "n/a"} else None

    try:
        return VisionResult(
            parcel_count=int(data.get("parcel_count") or 0),
            parcel_cut_off=bool(data.get("parcel_cut_off")),
            view_obstructed=bool(data.get("view_obstructed")),
            overlay_present=bool(data.get("overlay_present")),
            label_count=int(data.get("label_count") or 0),
            person_in_frame=bool(data.get("person_in_frame")),
            image_quality=str(data.get("image_quality") or "good"),
            overlay_awb=text_or_none("overlay_awb"),
            overlay_dimensions_text=text_or_none("overlay_dimensions_text"),
            overlay_weight_text=text_or_none("overlay_weight_text"),
            label_awb=text_or_none("label_awb"),
            notes=str(data.get("notes") or ""),
            model=model,
        )
    except (TypeError, ValueError):
        raise ValueError("wrong field types")


def create_vision_reader(api_key: str, model: str, enabled: bool, per_minute: int) -> Optional[VisionReader]:
    """None means offline mode (OCR + barcode only)."""
    if not enabled or not api_key:
        return None
    return GeminiVision(api_key, model, per_minute)
