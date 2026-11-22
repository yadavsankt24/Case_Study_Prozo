"""
Business rules for the daily FC P&L monitor (Case Study 3).

All thresholds live here so a rule change is a one-line edit.

Formulas (from the brief)
    CM1 = Revenue - Manpower - Packaging
    CM2 = CM1 - Power & Fuel - FC Rent - Equipment Rentals - Overheads
    Both are reported as % of revenue.

Colour code for each FC-day, based on CM2 %
    Red     CM2 < 12
    Yellow  12 <= CM2 < 15   or   30 < CM2 <= 33
    Green   15 <= CM2 <= 30
    Blue    CM2 > 33  (suspiciously high: check for unreported costs)
The brief leaves small gaps (14.9-15 and 32.9-33); values in a gap are treated
as Yellow because they are outside the healthy band but not yet Red / Blue.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cost lines, in the order they appear in the data
# ---------------------------------------------------------------------------
COST_LINES = ["Manpower", "Packaging", "Power & Fuel", "FC Rent", "Equipment Rentals", "Overheads"]
CM1_COSTS = ["Manpower", "Packaging"]                     # direct costs
CM2_COSTS = ["Power & Fuel", "FC Rent", "Equipment Rentals", "Overheads"]

# Spellings found in input files -> canonical line name
LINE_ALIASES = {
    "manpower": "Manpower", "manpower cost": "Manpower", "labour": "Manpower",
    "packaging": "Packaging", "packaging cost": "Packaging",
    "power and fuel": "Power & Fuel", "power & fuel": "Power & Fuel", "power fuel": "Power & Fuel",
    "fc rent": "FC Rent", "rent": "FC Rent",
    "equipment rentals": "Equipment Rentals", "equipment rental": "Equipment Rentals",
    "overheads": "Overheads", "overhead": "Overheads",
}

# Default target ranges (% of revenue) - the "Ideal FC Criteria" sheet of the sample.
# If an uploaded workbook carries its own criteria sheet, those values are used instead.
DEFAULT_TARGETS: dict[str, tuple[float, float]] = {
    "Manpower": (25, 27),
    "Packaging": (5, 7),
    "Power & Fuel": (10, 12),
    "FC Rent": (15, 18),
    "Equipment Rentals": (5, 8),
    "Overheads": (10, 12),
}

# ---------------------------------------------------------------------------
# Margin targets and tolerance
# ---------------------------------------------------------------------------
CM1_TARGET = (65.0, 70.0)
CM2_TARGET = (15.0, 30.0)
CM_TOLERANCE_PTS = 3.0   # flag CM1 / CM2 only when more than 3 points outside the target band

# ---------------------------------------------------------------------------
# Colour bands on CM2 %
# ---------------------------------------------------------------------------
RED_BELOW = 12.0
GREEN_FROM, GREEN_TO = 15.0, 30.0
BLUE_ABOVE = 33.0

# ---------------------------------------------------------------------------
# Severity of a cost-line breach (keeps the daily digest focused)
# ---------------------------------------------------------------------------
# A cost above its max by more than this many points is "medium", otherwise "low".
MEDIUM_BREACH_PTS = 2.0
TOP_CONTRIBUTORS_IN_DIGEST = 3

# ---------------------------------------------------------------------------
# Recommended actions
# ---------------------------------------------------------------------------
ACTION_ABOVE_MAX = {
    "Manpower": "review shift rosters and overtime against order volume",
    "Packaging": "check packaging material usage and wastage",
    "Power & Fuel": "check power bills and DG-set running hours",
    "FC Rent": "verify the rent entry (one-off or quarterly charge booked on one day?)",
    "Equipment Rentals": "review idle or extra equipment hires",
    "Overheads": "review discretionary overheads",
}
ACTION_BELOW_MIN = "confirm the cost was booked in full (possible under-reporting)"
ACTION_RED = "cost audit"
ACTION_BLUE = "verify all costs are booked - margins this high usually mean missing entries"

# Default first date for files that only number their days (Day 1, Day 2, ...).
# The brief's example ("On May 27 ...") matches Day 27 when Day 1 = 1 May.
DEFAULT_START_DATE = "2025-05-01"
