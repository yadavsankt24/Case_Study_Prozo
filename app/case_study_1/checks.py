"""
Cross-checks between independent reads. Pure functions, no I/O.

    vote_awb            which AWB do the readers agree on?
    compare_dimensions  do two reads of L x W x H agree?
    compare_weight      do two reads of the weight agree?
    volume_check        does a printed volume match L x W x H?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.case_study_1 import rules
from app.case_study_1.models import Dimensions, Measure, OverlayFields, VisionResult
from app.case_study_1.overlay_parser import normalise_awb, parse_dimensions_text, parse_overlay, parse_weight

OCR, GEMINI_OVERLAY, GEMINI_LABEL, BARCODE = "overlay OCR", "Gemini (overlay)", "Gemini (label)", "label barcode"


# ---------------------------------------------------------------- Gemini read -> fields

def vision_overlay_fields(vision: VisionResult) -> OverlayFields:
    """Parse Gemini's copy of the overlay with the same parser used for OCR."""
    fields = OverlayFields(awb=normalise_awb(vision.overlay_awb), awb_as_printed=vision.overlay_awb)
    text = vision.overlay_dimensions_text
    if text:
        fields.dimensions = (parse_dimensions_text(text)
                             or parse_overlay([text.replace(",", " ").replace(";", " ")]).dimensions)
    text = vision.overlay_weight_text
    if text:
        fields.weight = (parse_overlay([text]).weight if ":" in text else None) or parse_weight(text)
    return fields


# ---------------------------------------------------------------- AWB

@dataclass
class AwbVote:
    value: Optional[str] = None
    sources: list[str] = field(default_factory=list)       # readers that read `value`
    conflicts: dict[str, str] = field(default_factory=dict)  # reader -> a different value
    unmatched_barcodes: list[str] = field(default_factory=list)

    @property
    def confirmed_by_barcode(self) -> bool:
        return BARCODE in self.sources


def vote_awb(ocr_awb: Optional[str], vision: Optional[VisionResult], barcodes: list[str]) -> AwbVote:
    """
    Count how many independent readers read each AWB. Label barcodes count only when they
    equal another reader's value (labels also carry order numbers and other codes), or when
    a barcode is the only thing that could be read at all.
    """
    reads: dict[str, str] = {}
    if ocr_awb:
        reads[OCR] = ocr_awb
    if vision:
        if normalise_awb(vision.overlay_awb):
            reads[GEMINI_OVERLAY] = normalise_awb(vision.overlay_awb)
        if normalise_awb(vision.label_awb):
            reads[GEMINI_LABEL] = normalise_awb(vision.label_awb)
    codes = [c for c in (normalise_awb(b) for b in barcodes) if c]

    votes: dict[str, list[str]] = {}
    for reader, value in reads.items():
        votes.setdefault(value, []).append(reader)
    for code in codes:
        if code in votes:
            votes[code].append(BARCODE)
    if not votes and codes:
        votes[codes[0]] = [BARCODE]

    if not votes:
        return AwbVote(unmatched_barcodes=codes)
    best = max(votes, key=lambda v: len(votes[v]))
    conflicts = {reader: value for reader, value in reads.items() if value != best}
    return AwbVote(value=best, sources=votes[best], conflicts=conflicts,
                   unmatched_barcodes=[c for c in codes if c != best])


# ---------------------------------------------------------------- measures

def compare_dimensions(a: Optional[Dimensions], b: Optional[Dimensions]) -> Optional[bool]:
    """True = agree, False = disagree, None = fewer than two reads."""
    if not a or not b:
        return None
    return all(abs(x - y) <= rules.DIMENSION_AGREEMENT_CM for x, y in zip(a.as_cm(), b.as_cm()))


def compare_weight(a: Optional[Measure], b: Optional[Measure]) -> Optional[bool]:
    if not a or not b:
        return None
    return abs(a.value - b.value) <= rules.WEIGHT_AGREEMENT_KG


def dimensions_in_range(dimensions: Dimensions) -> bool:
    low, high = rules.DIMENSION_RANGE_CM
    return all(low <= v <= high for v in dimensions.as_cm())


def weight_in_range(weight: Measure) -> bool:
    low, high = rules.WEIGHT_RANGE_KG
    return low <= weight.value <= high


# ---------------------------------------------------------------- volume

# A printed volume may be in cm³, mm³ or m³; only its number is printed reliably.
VOLUME_SCALES = {"cm³": 1.0, "mm³": 1000.0, "m³": 1e-6}
# V.W is printed differently by each machine: L x W x H itself, or a courier volumetric weight (÷5000).
VOLUMETRIC_SCALES = {"cm³": 1.0, "kg (÷5000)": 1 / 5000, "g (÷5000)": 1000 / 5000}


@dataclass
class VolumeCheck:
    checked: bool = False
    passed: bool = False
    volume_cm3: Optional[float] = None
    detail: str = ""


def volume_check(dimensions: Optional[Dimensions], fields: OverlayFields) -> VolumeCheck:
    """
    Printed volume must match L x W x H within VOLUME_TOLERANCE. A mismatch means a digit
    or a unit was read wrongly. V.W is used only to confirm (machines compute it differently).
    """
    if not dimensions:
        return VolumeCheck()
    l, w, h = dimensions.as_cm()
    product = l * w * h
    if product <= 0:
        return VolumeCheck()

    if fields.volume_raw:
        for unit, scale in VOLUME_SCALES.items():
            expected = product * scale
            if abs(fields.volume_raw - expected) <= rules.VOLUME_TOLERANCE * expected:
                off = abs(fields.volume_raw - expected) / expected * 100
                return VolumeCheck(True, True, round(fields.volume_raw / scale, 1),
                                   f"printed volume matches L × W × H ({off:.1f}% apart, {unit})")
        return VolumeCheck(True, False, None,
                           f"printed volume {fields.volume_as_printed} does not match L × W × H ({product:,.0f} cm³)")

    if fields.volumetric_raw:
        for unit, scale in VOLUMETRIC_SCALES.items():
            expected = product * scale
            if abs(fields.volumetric_raw - expected) <= rules.VOLUME_TOLERANCE * expected:
                return VolumeCheck(True, True, round(product, 1), f"V.W matches L × W × H ({unit})")
    return VolumeCheck()
