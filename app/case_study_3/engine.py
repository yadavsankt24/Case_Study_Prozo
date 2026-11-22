"""
P&L engine: the deterministic heart of Case Study 3.

For each FC-day it
    1. calculates each cost as % of revenue, CM1, CM1 %, CM2, CM2 %
    2. assigns the colour (Red / Yellow / Green / Blue) from CM2 %
    3. flags cost lines outside their target range and CM1 / CM2 more than
       3 points outside their target band
    4. measures each flag's rupee impact so the causes can be ranked

No AI here: these numbers must be exact and repeatable.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.case_study_3 import rules
from app.case_study_3.models import Anomaly, Colour, DayInput, DayResult, Override, Severity


def colour_for(cm2_pct: float) -> Colour:
    if cm2_pct < rules.RED_BELOW:
        return Colour.RED
    if cm2_pct > rules.BLUE_ABOVE:
        return Colour.BLUE
    if rules.GREEN_FROM <= cm2_pct <= rules.GREEN_TO:
        return Colour.GREEN
    return Colour.YELLOW


def evaluate_day(row: DayInput, targets: dict[str, tuple[float, float]],
                 overrides: Iterable[Override] = ()) -> DayResult:
    revenue = row.revenue
    pct = {line: round(100 * row.costs[line] / revenue, 2) for line in rules.COST_LINES}
    cm1 = revenue - sum(row.costs[line] for line in rules.CM1_COSTS)
    cm2 = cm1 - sum(row.costs[line] for line in rules.CM2_COSTS)
    cm1_pct, cm2_pct = round(100 * cm1 / revenue, 2), round(100 * cm2 / revenue, 2)

    result = DayResult(
        fc=row.fc, day=row.day, revenue=revenue, costs=dict(row.costs), pct=pct,
        cm1=round(cm1, 2), cm1_pct=cm1_pct, cm2=round(cm2, 2), cm2_pct=cm2_pct,
        colour=colour_for(cm2_pct),
    )
    result.anomalies = _margin_anomalies(result) + _cost_anomalies(result, targets)

    for anomaly in result.anomalies:
        override = next((o for o in overrides if o.matches(anomaly)), None)
        if override:
            anomaly.acknowledged, anomaly.note = True, f"Known issue: {override.note}"

    # Most important first: severity, then money impact.
    order = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
    result.anomalies.sort(key=lambda a: (order[a.severity], -a.impact_rupees))
    return result


def _margin_anomalies(day: DayResult) -> list[Anomaly]:
    found = []
    for label, value, (low, high), severity in (
        ("CM1 %", day.cm1_pct, rules.CM1_TARGET, Severity.MEDIUM),
        ("CM2 %", day.cm2_pct, rules.CM2_TARGET, Severity.HIGH),
    ):
        flag_low, flag_high = low - rules.CM_TOLERANCE_PTS, high + rules.CM_TOLERANCE_PTS
        target_text = f"{low:g}-{high:g}% (flag outside {flag_low:g}-{flag_high:g}%)"
        if value < flag_low:
            found.append(Anomaly(day.fc, day.day, label, value, target_text, "Below target", severity,
                                 impact_rupees=0.0, deviation_pts=round(low - value, 2)))
        elif value > flag_high:
            found.append(Anomaly(day.fc, day.day, label, value, target_text, "Above target", severity,
                                 impact_rupees=0.0, deviation_pts=round(value - high, 2)))
    return found


def _cost_anomalies(day: DayResult, targets: dict[str, tuple[float, float]]) -> list[Anomaly]:
    found = []
    for line in rules.COST_LINES:
        low, high = targets[line]
        value = day.pct[line]
        if value > high:
            over = value - high
            severity = Severity.MEDIUM if over > rules.MEDIUM_BREACH_PTS else Severity.LOW
            found.append(Anomaly(day.fc, day.day, line, value, f"{low:g}-{high:g}%", "Above max", severity,
                                 impact_rupees=round(over / 100 * day.revenue), deviation_pts=round(over, 2)))
        elif value < low:
            under = low - value
            found.append(Anomaly(day.fc, day.day, line, value, f"{low:g}-{high:g}%", "Below min", Severity.LOW,
                                 impact_rupees=round(under / 100 * day.revenue), deviation_pts=round(under, 2)))
    return found


def scenario_of(day: DayResult) -> str:
    """Classify a day the way the brief's test cases are described."""
    labels = {a.line_item for a in day.anomalies}
    if day.colour == Colour.BLUE:
        return "suspiciously high CM2"
    if "CM2 %" in labels:
        return "CM2 breach"
    if not day.anomalies:
        return "clean day"
    if labels.isdisjoint({"CM1 %", "CM2 %"}):
        return "line-item-only breach"
    return "CM1 breach"


def latest_day(days: list[DayResult], fc: Optional[str] = None) -> Optional[DayResult]:
    candidates = [d for d in days if fc is None or d.fc == fc]
    return max(candidates, key=lambda d: d.day) if candidates else None
