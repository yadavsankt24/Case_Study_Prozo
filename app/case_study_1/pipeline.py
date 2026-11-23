"""
The pipeline for one frame. No web or database code, so the web app, the scripts
and the tests all run exactly this.

    1 image checks   does it open, is it big enough
    2 overlay OCR    offline text reading, grouped into rows
    3 parse          rows -> AWB, L / W / H, weight, volume, location, time, machine ID
                     (small frames with an incomplete read get a second OCR pass at 2x, merged)
    4 barcodes       offline barcode reading on the label
    5 vision         Gemini scene check + second read (skipped in offline mode)
    6 decide         cross-checks -> one status, confidence and record
"""

from __future__ import annotations

from typing import Optional

from PIL import Image

from app.case_study_1.barcode import read_barcodes
from app.case_study_1.decision import decide
from app.case_study_1.image_checks import check_image
from app.case_study_1.models import FrameResult, OverlayFields, VisionResult
from app.case_study_1.overlay_ocr import read_rows
from app.case_study_1 import rules
from app.case_study_1.overlay_parser import is_complete, merge_passes, parse_overlay
from app.case_study_1.vision import VisionReader


def process_frame(content: bytes, vision: Optional[VisionReader] = None) -> tuple[FrameResult, Optional[Image.Image]]:
    """Read one frame. Returns the record and the opened image (None if it could not be opened)."""
    image_check, image = check_image(content)
    if image is None:
        return decide(image_check, OverlayFields(), [], None, vision_enabled=vision is not None), None

    rows, ocr_error = read_rows(image)
    overlay = parse_overlay(rows)
    if not ocr_error and max(image.size) < rules.OCR_SECOND_PASS_BELOW_PX and not is_complete(overlay):
        rows_2x, _ = read_rows(image, upscale=2.0)
        if rows_2x:
            overlay = merge_passes(overlay, parse_overlay(rows_2x))
            rows = rows + ["--- second pass (2x) ---"] + rows_2x
    barcodes = read_barcodes(image)

    vision_result: Optional[VisionResult] = None
    vision_error: Optional[str] = None
    if vision is not None:
        vision_result, vision_error = vision.read(image)

    result = decide(image_check, overlay, barcodes, vision_result, vision_enabled=vision is not None,
                    vision_error=vision_error, ocr_error=ocr_error)
    result.readers["ocr"]["rows"] = rows
    return result, image
