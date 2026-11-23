"""
Decision: turn every reader's output into one record with one status.

Order (rules.STATUS_PRIORITY): a broken file, then scene problems seen by the vision
agent, then "nothing readable", then failed checks (NEEDS_REVIEW), then OK.

Values reach the clean CSV columns only for OK frames: the AWB must be read the same
by two independent readers, and every other value must agree and pass its checks.
In offline mode (no vision agent) a single read is accepted with LOW confidence.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from app.case_study_1 import rules
from app.case_study_1.checks import (AwbVote, compare_dimensions, compare_weight, dimensions_in_range,
                                     vision_overlay_fields, volume_check, vote_awb, weight_in_range)
from app.case_study_1.image_checks import quality_hint
from app.case_study_1.models import (Confidence, Dimensions, FrameResult, ImageCheck, Measure, OverlayFields,
                                     Status, VisionResult)


def decide(
    image: ImageCheck,
    ocr: OverlayFields,
    barcodes: list[str],
    vision: Optional[VisionResult],
    vision_enabled: bool,
    vision_error: Optional[str] = None,
    ocr_error: Optional[str] = None,
) -> FrameResult:
    readers = _audit(image, ocr, barcodes, vision, vision_error, ocr_error)

    if not image.ok:
        return FrameResult(Status.INVALID_IMAGE, _sentence(image.problem), Confidence.LOW, readers=readers)

    result = _evidence(ocr, barcodes, readers)
    if vision_enabled and vision is None:
        result.status, result.confidence = Status.PROCESSING_ERROR, Confidence.LOW
        result.status_reason = f"The vision check failed: {vision_error or 'no answer'}. The frame can be re-run."
        return result

    vision_fields = vision_overlay_fields(vision) if vision else OverlayFields()
    vote = vote_awb(ocr.awb, vision, barcodes)
    dimensions, dim_notes, dim_review = _pick_dimensions(ocr.dimensions, vision_fields.dimensions, vision_enabled)
    weight, weight_notes, weight_review = _pick_weight(ocr.weight, vision_fields.weight, vision_enabled)
    volume = volume_check(dimensions, ocr)

    notes = _scene_notes(vision) + dim_notes + weight_notes
    review: list[str] = list(ocr.problems) + dim_review + weight_review
    if volume.checked and not volume.passed:
        review.append(volume.detail)
    elif volume.passed:
        notes.append(volume.detail)
    if dimensions and dimensions.unit_inferred:
        notes.append(f"dimension unit not printed: read as {dimensions.length.unit}")
    if weight and weight.unit_inferred:
        notes.append(f"weight unit not printed: read as {weight.unit}")

    confidence, awb_review, awb_notes = _judge_awb(vote, vision_enabled)
    review += awb_review
    notes += awb_notes
    if not vision_enabled:
        notes.append("offline mode: scene not checked by the vision agent")

    scene = _scene_status(vision)
    if scene:
        status, reason = scene
    elif not vote.value and not ocr.found_anything and not vision_fields.found_anything:
        hint = quality_hint(image)
        status, reason = Status.UNREADABLE, "No machine readings and no readable label" + (f" ({hint})." if hint else ".")
    elif review:
        status, reason = Status.NEEDS_REVIEW, _sentence("; ".join(dict.fromkeys(review)))
    else:
        status, reason = Status.OK, _ok_reason(vote)

    result.status, result.status_reason = status, reason
    result.confidence = confidence if status == Status.OK else Confidence.LOW
    result.notes = list(dict.fromkeys(notes))
    result.units_inferred = bool((dimensions and dimensions.unit_inferred) or (weight and weight.unit_inferred))
    if status == Status.OK or rules.FLAGGED_ROWS_KEEP_VALUES:
        _fill_clean_columns(result, vote.value, dimensions, weight, volume.volume_cm3)
    return result


# ---------------------------------------------------------------- AWB

def _judge_awb(vote: AwbVote, vision_enabled: bool) -> tuple[Confidence, list[str], list[str]]:
    review, notes = [], []
    if vote.conflicts:
        review.append("readers disagree on the AWB: " + ", ".join(
            [f"{'/'.join(vote.sources)} read {vote.value}"] + [f"{r} read {v}" for r, v in vote.conflicts.items()]))
    if vote.value and len(vote.sources) < 2 and not vote.conflicts:
        if vision_enabled:
            review.append(f"AWB read by only one reader ({vote.sources[0]})")
        else:
            notes.append(f"AWB from a single read ({vote.sources[0]})")
    if vote.unmatched_barcodes:
        notes.append("other barcodes on the label: " + ", ".join(vote.unmatched_barcodes))
    if vote.confirmed_by_barcode and len(vote.sources) >= 2:
        notes.append("label barcode matches the AWB")
    if vote.value and len(vote.sources) >= 2:
        confidence = Confidence.HIGH if vote.confirmed_by_barcode else Confidence.MEDIUM
    else:
        confidence = Confidence.LOW
    return confidence, review, notes


def _ok_reason(vote: AwbVote) -> str:
    if len(vote.sources) >= 2:
        return "AWB read the same by " + _join(vote.sources) + "; other values checked."
    return f"Read by {vote.sources[0]} only (offline mode); values checked." if vote.sources else "Values checked."


# ---------------------------------------------------------------- measures

def _pick_dimensions(ocr: Optional[Dimensions], gemini: Optional[Dimensions], vision_enabled: bool):
    notes, review = [], []
    agree = compare_dimensions(ocr, gemini)
    chosen = ocr or gemini
    if agree is False:
        review.append(f"dimensions read differently: OCR {_dims(ocr)} vs Gemini {_dims(gemini)}")
    elif agree is None and chosen and vision_enabled:
        review.append(f"dimensions read by only one reader ({'OCR' if ocr else 'Gemini'})")
    if chosen and not dimensions_in_range(chosen):
        review.append(f"dimensions out of range ({_dims(chosen)})")
    if not chosen:
        notes.append("dimensions not printed")
    return chosen, notes, review


def _pick_weight(ocr: Optional[Measure], gemini: Optional[Measure], vision_enabled: bool):
    notes, review = [], []
    agree = compare_weight(ocr, gemini)
    chosen = ocr or gemini
    if agree is False:
        review.append(f"weight read differently: OCR {ocr.value} kg vs Gemini {gemini.value} kg")
    elif agree is None and chosen and vision_enabled:
        review.append(f"weight read by only one reader ({'OCR' if ocr else 'Gemini'})")
    if chosen and not weight_in_range(chosen):
        review.append(f"weight out of range ({chosen.value} kg)")
    if not chosen:
        notes.append("weight not printed")
    return chosen, notes, review


# ---------------------------------------------------------------- scene

def _scene_status(vision: Optional[VisionResult]) -> Optional[tuple[Status, str]]:
    if not vision:
        return None
    if vision.parcel_count == 0:
        return Status.NO_PARCEL, "No parcel in the frame."
    if vision.parcel_count > 1:
        return Status.MULTIPLE_PARCELS, f"{vision.parcel_count} parcels in the frame, so the readings can't be tied to one parcel."
    if vision.parcel_cut_off:
        return Status.PARCEL_PARTIAL, "Parcel only partly captured; the machine readings may be wrong."
    if vision.view_obstructed:
        return Status.VIEW_OBSTRUCTED, "Something covers the parcel or its label."
    return None


def _scene_notes(vision: Optional[VisionResult]) -> list[str]:
    if not vision:
        return []
    notes = []
    if vision.person_in_frame and not vision.view_obstructed:
        notes.append("person in frame (not covering the parcel)")
    if vision.label_count > 1:
        notes.append(f"{vision.label_count} labels on one parcel")
    if vision.image_quality != "good":
        notes.append(f"image quality: {vision.image_quality}")
    return notes


# ---------------------------------------------------------------- output

def _evidence(ocr: OverlayFields, barcodes: list[str], readers: dict) -> FrameResult:
    result = FrameResult(Status.OK, "", Confidence.LOW, readers=readers)
    result.location, result.scan_time, result.machine_id = ocr.location, ocr.scan_time, ocr.machine_id
    result.awb_as_read = ocr.awb_as_printed
    result.dimensions_as_read = ocr.dimensions.as_printed if ocr.dimensions else None
    result.weight_as_read = ocr.weight.as_printed if ocr.weight else None
    result.label_barcodes = list(barcodes)
    return result


def _fill_clean_columns(result: FrameResult, awb, dimensions, weight, volume_cm3) -> None:
    result.awb = awb
    if dimensions:
        result.length_cm, result.width_cm, result.height_cm = dimensions.as_cm()
    if weight:
        result.weight_kg = weight.value
    result.volume_cm3 = volume_cm3


def _audit(image, ocr, barcodes, vision, vision_error, ocr_error) -> dict:
    """Everything each reader returned, stored with the record so any value can be traced."""
    return {
        "image": asdict(image),
        "ocr": {"awb": ocr.awb, "dimensions": list(ocr.dimensions.as_cm()) if ocr.dimensions else None,
                "weight_kg": ocr.weight.value if ocr.weight else None, "volume": ocr.volume_as_printed,
                "problems": ocr.problems, "error": ocr_error},
        "barcodes": list(barcodes),
        "vision": asdict(vision) if vision else None,
        "vision_error": vision_error,
    }


def _dims(d: Optional[Dimensions]) -> str:
    return " × ".join(f"{v:g}" for v in d.as_cm()) + " cm" if d else "-"


def _sentence(text: str) -> str:
    """First letter upper case, full stop at the end. (str.capitalize() would lower-case 'AWB' and 'OCR'.)"""
    text = text.strip()
    return (text[:1].upper() + text[1:]).rstrip(".") + "." if text else ""


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
