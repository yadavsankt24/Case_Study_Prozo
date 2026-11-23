"""
Offline OCR of a frame (RapidOCR, ONNX runtime - no internet, no API key).

Returns the text grouped into rows, left to right, so a key and its value printed
side by side ("AWB_No:"  "19108610787894") end up on the same row for the parser.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import threading
from dataclasses import dataclass
from statistics import median
from typing import Optional

import numpy as np
from PIL import Image

from app.case_study_1 import rules

log = logging.getLogger(__name__)

_engine = None
_engine_lock = threading.Lock()


@dataclass
class TextBox:
    text: str
    x: float
    y: float          # vertical centre
    height: float
    score: float


def _get_engine():
    """Load the OCR models once (about a second) and share them between workers."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def ocr_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


KEY_ONLY = re.compile(r"[A-Za-z.]{1,4}\s*:")


def read_boxes(image: Image.Image, upscale: float = 1.0) -> list[TextBox]:
    """
    Text boxes with a confidence of at least OCR_MIN_SCORE. Short key-only boxes such as
    "L:" are kept from OCR_KEY_MIN_SCORE: they hold no digits, so they can't add a wrong value.
    """
    scaled = image.convert("RGB")
    scale = min(upscale, rules.OCR_MAX_SIDE_PX / max(scaled.size)) if upscale > 1 else 1.0
    longest = max(scaled.size)
    if upscale <= 1 and longest > rules.OCR_MAX_SIDE_PX:
        scale = rules.OCR_MAX_SIDE_PX / longest
    if scale != 1.0:
        scaled = scaled.resize((int(scaled.width * scale), int(scaled.height * scale)), Image.LANCZOS)
    with _engine_lock:                       # the ONNX session is shared; one call at a time
        # OpenCV-style models expect BGR channel order (red overlay text is misread otherwise)
        result, _ = _get_engine()(np.ascontiguousarray(np.asarray(scaled)[:, :, ::-1]))
    boxes = []
    for points, text, score in result or []:
        text, score = str(text).strip(), float(score)
        if not text or score < (rules.OCR_KEY_MIN_SCORE if KEY_ONLY.fullmatch(text) else rules.OCR_MIN_SCORE):
            continue
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]
        boxes.append(TextBox(text, min(xs) / scale, (min(ys) + max(ys)) / 2 / scale,
                             (max(ys) - min(ys)) / scale, score))
    return boxes


def group_rows(boxes: list[TextBox]) -> list[str]:
    """Group boxes whose vertical centres are close into rows; order each row left to right."""
    if not boxes:
        return []
    typical_height = median(b.height for b in boxes) or 1.0
    rows: list[list[TextBox]] = []
    for box in sorted(boxes, key=lambda b: b.y):
        if rows and abs(box.y - _row_centre(rows[-1])) <= 0.5 * max(typical_height, box.height):
            rows[-1].append(box)
        else:
            rows.append([box])
    return [" ".join(b.text for b in sorted(row, key=lambda b: b.x)) for row in rows]


def _row_centre(row: list[TextBox]) -> float:
    return sum(b.y for b in row) / len(row)


def read_rows(image: Image.Image, upscale: float = 1.0) -> tuple[list[str], Optional[str]]:
    """(rows, error). Never raises: an OCR failure is reported, not fatal."""
    try:
        return group_rows(read_boxes(image, upscale)), None
    except Exception as exc:  # model files missing, corrupt image data ...
        log.warning("OCR failed: %s", exc)
        return [], f"OCR failed: {exc}"
