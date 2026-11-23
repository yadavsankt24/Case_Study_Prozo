"""
Cross-checks and the decision. The vision results here are hand-written stand-ins for
Gemini's answer (no network in tests), so each rule can be tested on its own.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.case_study_1 import rules
from app.case_study_1.checks import vote_awb, volume_check
from app.case_study_1.decision import decide
from app.case_study_1.models import Confidence, ImageCheck, OverlayFields, Status, VisionResult
from app.case_study_1.overlay_parser import parse_overlay

GOOD_IMAGE = ImageCheck(ok=True, width=1400, height=900, brightness=60, sharpness=200)
OVERLAY = parse_overlay(["AWB_NO :77873372404", "LENGTH(cm) : 21.40", "WIDTH(cm) : 16.40",
                         "HEIGHT(cm) : 6.20", "WEIGHT(Kg) : 0.58"])
CLEAR = VisionResult(parcel_count=1, parcel_cut_off=False, view_obstructed=False, overlay_present=True,
                     label_count=1, person_in_frame=False, image_quality="good", overlay_awb="77873372404",
                     overlay_dimensions_text="LENGTH(cm): 21.40, WIDTH(cm): 16.40, HEIGHT(cm): 6.20",
                     overlay_weight_text="0.58 Kg", label_awb="77873372404")


def test_clean_frame_with_all_readers_is_ok_high():
    result = decide(GOOD_IMAGE, OVERLAY, ["77873372404"], CLEAR, vision_enabled=True)
    assert result.status == Status.OK and result.confidence == Confidence.HIGH
    assert (result.awb, result.length_cm, result.width_cm, result.height_cm, result.weight_kg) == (
        "77873372404", 21.4, 16.4, 6.2, 0.58)
    assert "label barcode matches the AWB" in result.notes


def test_two_reads_without_barcode_is_medium():
    result = decide(GOOD_IMAGE, OVERLAY, [], replace(CLEAR, label_awb=None), vision_enabled=True)
    assert result.status == Status.OK and result.confidence == Confidence.MEDIUM


@pytest.mark.parametrize("change, status", [
    ({"parcel_count": 0}, Status.NO_PARCEL),
    ({"parcel_count": 2}, Status.MULTIPLE_PARCELS),
    ({"parcel_cut_off": True}, Status.PARCEL_PARTIAL),
    ({"view_obstructed": True}, Status.VIEW_OBSTRUCTED),
])
def test_scene_flags_blank_the_clean_columns(change, status):
    result = decide(GOOD_IMAGE, OVERLAY, ["77873372404"], replace(CLEAR, **change), vision_enabled=True)
    assert result.status == status and result.confidence == Confidence.LOW
    assert result.awb is None and result.weight_kg is None
    assert result.awb_as_read == "77873372404"                      # evidence is kept


def test_flagged_rows_can_keep_values(monkeypatch):
    monkeypatch.setattr(rules, "FLAGGED_ROWS_KEEP_VALUES", True)
    result = decide(GOOD_IMAGE, OVERLAY, [], replace(CLEAR, parcel_cut_off=True), vision_enabled=True)
    assert result.status == Status.PARCEL_PARTIAL and result.awb == "77873372404"


def test_readers_disagree_goes_to_review():
    result = decide(GOOD_IMAGE, OVERLAY, [], replace(CLEAR, overlay_awb="77873372407", label_awb=None),
                    vision_enabled=True)
    assert result.status == Status.NEEDS_REVIEW
    assert "Readers disagree on the AWB" in result.status_reason and result.awb is None


def test_label_awb_different_from_machine_awb_goes_to_review():
    result = decide(GOOD_IMAGE, OVERLAY, [], replace(CLEAR, label_awb="77873372499"), vision_enabled=True)
    assert result.status == Status.NEEDS_REVIEW


def test_single_read_needs_review_when_vision_is_on_but_is_ok_low_offline():
    lonely = replace(CLEAR, overlay_awb=None, label_awb=None)
    assert decide(GOOD_IMAGE, OVERLAY, [], lonely, vision_enabled=True).status == Status.NEEDS_REVIEW
    offline = decide(GOOD_IMAGE, OVERLAY, [], None, vision_enabled=False)
    assert offline.status == Status.OK and offline.confidence == Confidence.LOW
    assert "offline mode: scene not checked by the vision agent" in offline.notes


def test_dimensions_read_differently_go_to_review():
    result = decide(GOOD_IMAGE, OVERLAY, [], replace(CLEAR, overlay_dimensions_text="31.4 x 16.4 x 6.2 cm"),
                    vision_enabled=True)
    assert result.status == Status.NEEDS_REVIEW and "dimensions read differently" in result.status_reason.lower()


def test_out_of_range_weight_goes_to_review():
    heavy = parse_overlay(["AWB_NO :77873372404", "WEIGHT(Kg) : 250"])
    result = decide(GOOD_IMAGE, heavy, [], None, vision_enabled=False)
    assert result.status == Status.NEEDS_REVIEW and "weight out of range" in result.status_reason.lower()


def test_vision_failure_is_processing_error_with_evidence():
    result = decide(GOOD_IMAGE, OVERLAY, [], None, vision_enabled=True, vision_error="Gemini returned 503")
    assert result.status == Status.PROCESSING_ERROR and "503" in result.status_reason
    assert result.awb_as_read == "77873372404"


def test_nothing_readable_is_unreadable_with_a_hint():
    dark = ImageCheck(ok=True, width=1400, height=900, brightness=8, sharpness=3)
    result = decide(dark, OverlayFields(), [], None, vision_enabled=False)
    assert result.status == Status.UNREADABLE and "very dark" in result.status_reason


def test_invalid_image():
    result = decide(ImageCheck(ok=False, problem="the file is not a readable image"), OverlayFields(), [], None, False)
    assert result.status == Status.INVALID_IMAGE


def test_barcode_votes():
    vote = vote_awb("19108610906662", None, ["19108610906662", "2023409261"])
    assert vote.value == "19108610906662" and vote.confirmed_by_barcode
    assert vote.unmatched_barcodes == ["2023409261"]                    # order numbers on labels are ignored
    assert vote_awb(None, None, ["77873372404"]).sources == ["label barcode"]   # label only: single read


def test_volume_check():
    fields = parse_overlay(["Dimension: 0208X0148X0163", "Volume: 005134809"])
    check = volume_check(fields.dimensions, fields)
    assert check.passed and check.volume_cm3 == 5134.8 and "mm³" in check.detail
    wrong = parse_overlay(["Length: 35.9 cm", "Width: 34.5 cm", "Height: 15.7 cm", "R.Vol.: 27202 cm (cubic)"])
    assert volume_check(wrong.dimensions, wrong).passed is False
