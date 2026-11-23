"""The whole per-frame pipeline on the 5 sample frames and a few generated ones (offline readers are real)."""

from __future__ import annotations

import csv

import pytest

from app.case_study_1.models import Status, VisionResult
from app.case_study_1.pipeline import process_frame
from tests.conftest import CS1_SAMPLE


def answer_key(folder):
    with open(folder / "answer_key.csv", newline="") as handle:
        return {row["image_file"]: row for row in csv.DictReader(handle)}


@pytest.mark.parametrize("name", sorted(answer_key(CS1_SAMPLE)))
def test_sample_frames_offline(name):
    expected = answer_key(CS1_SAMPLE)[name]
    result, _ = process_frame((CS1_SAMPLE / name).read_bytes())
    assert result.status.value == expected["expected_status_offline"]
    assert result.awb == expected["awb"]
    assert (result.length_cm, result.width_cm, result.height_cm) == tuple(
        float(expected[k]) for k in ("length_cm", "width_cm", "height_cm"))
    assert result.weight_kg == (float(expected["weight_kg"]) if expected["weight_kg"] else None)


class StubVision:
    """Stands in for Gemini: returns a fixed answer (what Gemini would say about the half-captured frame)."""
    name = "stub"

    def __init__(self, **answer):
        self.answer = VisionResult(**{**dict(parcel_count=1, parcel_cut_off=False, view_obstructed=False,
                                             overlay_present=True, label_count=1, person_in_frame=False,
                                             image_quality="good", overlay_awb=None, overlay_dimensions_text=None,
                                             overlay_weight_text=None, label_awb=None), **answer})

    def read(self, image):
        return self.answer, None


def test_half_captured_frame_is_flagged_with_vision():
    name = "Half shipment captured_png.rf.WNrelVB6aeQO3rpN0eiY.png"
    result, _ = process_frame((CS1_SAMPLE / name).read_bytes(),
                              StubVision(parcel_cut_off=True, overlay_awb="19108610817924"))
    assert result.status == Status.PARCEL_PARTIAL
    assert result.awb is None and result.awb_as_read == "19108610817924"


def test_two_readers_agree_on_a_sample_frame():
    name = "download (2)_jpeg.rf.bo0zLhZTso7FTTzLvhqL.jpeg"
    result, _ = process_frame((CS1_SAMPLE / name).read_bytes(), StubVision(
        overlay_awb="19108610906662", label_count=2,
        overlay_dimensions_text="Length: 35.900 cm, Width: 34.500 cm, Height: 15.700 cm",
        overlay_weight_text="Weight: 2210.000 gm"))
    assert result.status == Status.OK and result.confidence.value == "high"     # OCR + Gemini + barcode
    assert "2 labels on one parcel" in result.notes


@pytest.mark.parametrize("name, status", [
    ("22_volume_mismatch_1.jpg", "NEEDS_REVIEW"),
    ("33_label_only_1.jpg", "OK"),
    ("35_unreadable_blurred_1.jpg", "UNREADABLE"),
    ("40_corrupt_file.jpg", "INVALID_IMAGE"),
    ("41_tiny_image.jpg", "INVALID_IMAGE"),
])
def test_generated_frames_offline(cs1_generated, name, status):
    result, _ = process_frame((cs1_generated / name).read_bytes())
    assert result.status.value == status
