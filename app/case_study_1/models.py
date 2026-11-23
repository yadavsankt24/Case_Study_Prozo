"""Data shapes for Case Study 1. Plain dataclasses: no framework or database code."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class Status(str, Enum):
    OK = "OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NO_PARCEL = "NO_PARCEL"
    MULTIPLE_PARCELS = "MULTIPLE_PARCELS"
    PARCEL_PARTIAL = "PARCEL_PARTIAL"
    VIEW_OBSTRUCTED = "VIEW_OBSTRUCTED"
    UNREADABLE = "UNREADABLE"
    INVALID_IMAGE = "INVALID_IMAGE"
    PROCESSING_ERROR = "PROCESSING_ERROR"


class Confidence(str, Enum):
    HIGH = "high"      # two reads agree and a label barcode confirms the AWB
    MEDIUM = "medium"  # two independent reads agree
    LOW = "low"        # a single read (offline mode) or a flagged frame


@dataclass
class Measure:
    """One number read from a frame, converted to a standard unit."""
    value: float                  # in cm (dimensions) or kg (weight)
    as_printed: str               # the text exactly as read, e.g. "01190" or "2210.000 gm"
    unit: str                     # unit used: as printed, or inferred when unit_inferred is True
    unit_inferred: bool = False


@dataclass
class Dimensions:
    length: Measure
    width: Measure
    height: Measure

    def as_cm(self) -> tuple[float, float, float]:
        return self.length.value, self.width.value, self.height.value

    @property
    def unit_inferred(self) -> bool:
        return self.length.unit_inferred

    @property
    def as_printed(self) -> str:
        texts = {self.length.as_printed, self.width.as_printed, self.height.as_printed}
        if len(texts) == 1:                       # one string such as "0208 X 0148 X 0163"
            return self.length.as_printed
        return f"L {self.length.as_printed} · W {self.width.as_printed} · H {self.height.as_printed}"


@dataclass
class OverlayFields:
    """What the parser found in the machine's text overlay (or in a vision read of it)."""
    awb: Optional[str] = None
    awb_as_printed: Optional[str] = None
    dimensions: Optional[Dimensions] = None
    weight: Optional[Measure] = None
    volume_raw: Optional[float] = None          # number as printed, unit unknown
    volume_as_printed: Optional[str] = None
    volumetric_as_printed: Optional[str] = None
    volumetric_raw: Optional[float] = None
    location: Optional[str] = None
    scan_time: Optional[str] = None
    machine_id: Optional[str] = None
    problems: list[str] = field(default_factory=list)   # e.g. "two different AWBs printed"

    @property
    def found_anything(self) -> bool:
        return bool(self.awb or self.dimensions or self.weight)


@dataclass
class VisionResult:
    """Gemini's answer for one frame (scene check + its own read)."""
    parcel_count: int
    parcel_cut_off: bool
    view_obstructed: bool
    overlay_present: bool
    label_count: int
    person_in_frame: bool
    image_quality: str                       # good | blurred | dark | glare
    overlay_awb: Optional[str]
    overlay_dimensions_text: Optional[str]
    overlay_weight_text: Optional[str]
    label_awb: Optional[str]
    notes: str = ""
    model: str = ""


@dataclass
class ImageCheck:
    ok: bool
    width: int = 0
    height: int = 0
    brightness: float = 0.0     # 0-255 mean
    sharpness: float = 0.0      # edge variance; low = blurred
    problem: str = ""


@dataclass
class FrameResult:
    """The final record for one frame. One row of the CSV."""
    status: Status
    status_reason: str
    confidence: Confidence
    awb: Optional[str] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    volume_cm3: Optional[float] = None
    location: Optional[str] = None
    scan_time: Optional[str] = None
    machine_id: Optional[str] = None
    awb_as_read: Optional[str] = None
    dimensions_as_read: Optional[str] = None
    weight_as_read: Optional[str] = None
    label_barcodes: list[str] = field(default_factory=list)
    units_inferred: bool = False
    notes: list[str] = field(default_factory=list)
    readers: dict = field(default_factory=dict)   # raw output of each reader, for audit

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["confidence"] = self.confidence.value
        return data
