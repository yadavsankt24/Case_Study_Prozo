"""Domain models for Case Study 3 (framework-free dataclasses)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Colour(str, Enum):
    RED = "Red"
    YELLOW = "Yellow"
    GREEN = "Green"
    BLUE = "Blue"


class Severity(str, Enum):
    HIGH = "high"      # CM2 breach (Red / Blue day)
    MEDIUM = "medium"  # CM1 breach, or a cost well above its max
    LOW = "low"        # small overrun, or a cost below its min


@dataclass
class DayInput:
    """One row of input: revenue and costs for one FC on one day."""

    fc: str
    day: date
    revenue: float
    costs: dict[str, float]          # line name -> rupees
    source_row: int = 0


@dataclass
class Anomaly:
    """One flagged item: a row of the anomaly log."""

    fc: str
    day: date
    line_item: str                   # cost line, or "CM1 %" / "CM2 %"
    pct_of_revenue: float
    target_range: str                # e.g. "25-27%", or "65-70% (flag outside 62-73%)"
    status: str                      # "Above max", "Below min", "Below target", "Above target"
    severity: Severity
    impact_rupees: float             # money effect vs the nearest limit (0 for CM rows)
    deviation_pts: float             # how far outside the limit, in percentage points
    acknowledged: bool = False       # matched a manager override ("known issue")
    note: str = ""


@dataclass
class DayResult:
    """Computed P&L, flags and insight for one FC-day."""

    fc: str
    day: date
    revenue: float
    costs: dict[str, float]
    pct: dict[str, float]            # line name -> % of revenue
    cm1: float
    cm1_pct: float
    cm2: float
    cm2_pct: float
    colour: Colour
    anomalies: list[Anomaly] = field(default_factory=list)
    insight: str = ""
    action: str = ""

    @property
    def is_clean(self) -> bool:
        return not self.anomalies

    @property
    def open_anomalies(self) -> list[Anomaly]:
        return [a for a in self.anomalies if not a.acknowledged]


@dataclass
class Override:
    """A manager's 'known issue' note: matching anomalies are kept in the log but left out of alerts."""

    fc: str
    line_item: str
    date_from: date
    date_to: date
    note: str

    def matches(self, anomaly: Anomaly) -> bool:
        return (anomaly.fc == self.fc and anomaly.line_item == self.line_item
                and self.date_from <= anomaly.day <= self.date_to)


@dataclass
class Trend:
    """Memory of past days for one FC, used in the digest."""

    streak_colour: Optional[Colour] = None
    streak_days: int = 0                 # consecutive days with the same non-green colour, incl. today
    avg_cm2_7d: Optional[float] = None
    prev_cm2: Optional[float] = None


@dataclass
class IngestResult:
    rows: list[DayInput]
    targets: dict[str, tuple[float, float]]
    targets_source: str                  # "file" or "defaults"
    warnings: list[str]
