"""
Every Case Study 1 rule in one place: flag priority, overlay key names, units,
plausible ranges and tolerances.

A new scanning-machine layout usually needs only a new key alias here.
Keys are compared in "squashed" form: lower case, letters and digits only
("AWB_No:" -> "awbno", "A.W" -> "aw", "LENGTH(cm)" -> "length" + unit "cm").
"""

from __future__ import annotations

from app.case_study_1.models import Status

# ---------------------------------------------------------------- flags

# When several problems apply, the first one in this list wins (it explains the others).
STATUS_PRIORITY = [
    Status.INVALID_IMAGE,
    Status.NO_PARCEL,
    Status.MULTIPLE_PARCELS,
    Status.PARCEL_PARTIAL,
    Status.VIEW_OBSTRUCTED,
    Status.UNREADABLE,
    Status.PROCESSING_ERROR,
    Status.NEEDS_REVIEW,
    Status.OK,
]

# Flagged frames keep what was read in the evidence columns. Set True to also fill the
# clean columns (awb, weight_kg, ...) for flagged frames. Waiting for Prozo's decision.
FLAGGED_ROWS_KEEP_VALUES = False

# ---------------------------------------------------------------- overlay keys

AWB_KEY_ALIASES = {"awb", "awbno", "awbnumber", "awbnum", "barcode", "waybill", "waybillno", "shipmentno"}
LENGTH_KEY_ALIASES = {"l", "length", "len"}
WIDTH_KEY_ALIASES = {"w", "width", "b", "breadth"}
HEIGHT_KEY_ALIASES = {"h", "height", "ht"}
DIMENSIONS_KEY_ALIASES = {"dimension", "dimensions", "dim", "dims", "lbh", "lwh", "size"}
WEIGHT_KEY_ALIASES = {"weight", "wt", "aw", "actualweight", "grossweight", "deadweight", "netweight"}
VOLUMETRIC_KEY_ALIASES = {"vw", "volumetricweight", "volweight", "volwt"}
VOLUME_KEY_ALIASES = {"volume", "vol", "rvol", "rvolume"}
LOCATION_KEY_ALIASES = {"location", "locationcode", "site", "hub"}
TIME_KEY_ALIASES = {"time", "datetime", "timestamp", "date", "scantime"}
MACHINE_KEY_ALIASES = {"sorterid", "id", "mid", "machineid", "deviceid", "sorter", "device"}

FIELD_ALIASES = {
    "awb": AWB_KEY_ALIASES,
    "length": LENGTH_KEY_ALIASES,
    "width": WIDTH_KEY_ALIASES,
    "height": HEIGHT_KEY_ALIASES,
    "dimensions": DIMENSIONS_KEY_ALIASES,
    "weight": WEIGHT_KEY_ALIASES,
    "volumetric": VOLUMETRIC_KEY_ALIASES,
    "volume": VOLUME_KEY_ALIASES,
    "location": LOCATION_KEY_ALIASES,
    "scan_time": TIME_KEY_ALIASES,
    "machine_id": MACHINE_KEY_ALIASES,
}

# ---------------------------------------------------------------- AWB

AWB_PATTERN = r"^[A-Z0-9]{8,20}$"

# ---------------------------------------------------------------- units and ranges

LENGTH_UNITS_TO_CM = {"mm": 0.1, "cm": 1.0, "m": 100.0, "in": 2.54, "inch": 2.54, "inches": 2.54}
WEIGHT_UNITS_TO_KG = {"g": 0.001, "gm": 0.001, "gms": 0.001, "gram": 0.001, "grams": 0.001,
                      "kg": 1.0, "kgs": 1.0, "lb": 0.4536, "lbs": 0.4536}

DIMENSION_RANGE_CM = (1.0, 250.0)
WEIGHT_RANGE_KG = (0.01, 100.0)

# No unit printed: a weight written as an integer of at least this value is grams ("01190" -> 1.19 kg).
WEIGHT_GRAMS_IF_INTEGER_AT_LEAST = 100
# No unit printed: zero-padded integers of this many digits are millimetres ("0208" -> 20.8 cm).
DIMENSION_MM_PADDED_DIGITS = 4

# Printed volume (or V.W) must be within this fraction of L x W x H.
VOLUME_TOLERANCE = 0.05

# Two reads of a dimension or weight agree when they differ by no more than this.
DIMENSION_AGREEMENT_CM = 0.5
WEIGHT_AGREEMENT_KG = 0.02

# ---------------------------------------------------------------- images

MIN_IMAGE_SIDE_PX = 200
OCR_MAX_SIDE_PX = 2000          # larger frames are scaled down before OCR (faster, same accuracy)
VISION_MAX_SIDE_PX = 1600       # frames sent to Gemini are scaled down to this
THUMBNAIL_MAX_SIDE_PX = 480
OCR_MIN_SCORE = 0.6
OCR_KEY_MIN_SCORE = 0.3          # key-only boxes such as "L:" (no digits, so no risk of a wrong value)
# Frames smaller than this whose first read is incomplete get a second OCR pass at 2x;
# the two passes are merged and any disagreement goes to review.
OCR_SECOND_PASS_BELOW_PX = 1500
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
