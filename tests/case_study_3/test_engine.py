"""Case Study 3: P&L formulas, colour bands, flags, impact ranking and insights."""

from __future__ import annotations

from datetime import date

import pytest

from app.case_study_3 import rules
from app.case_study_3.engine import colour_for, evaluate_day, scenario_of
from app.case_study_3.insights import write_insight
from app.case_study_3.models import Colour, DayInput, Override, Severity

TARGETS = rules.DEFAULT_TARGETS


def make_day(revenue=100_000, **pct) -> DayInput:
    """Build a day from cost percentages (defaults are mid-range, i.e. a clean day)."""
    mix = {"Manpower": 26, "Packaging": 6, "Power & Fuel": 11, "FC Rent": 16.5, "Equipment Rentals": 6.5,
           "Overheads": 11}
    mix.update({k.replace("_", " ").replace("and", "&"): v for k, v in pct.items()})
    return DayInput(fc="FC-T", day=date(2025, 5, 27), revenue=revenue,
                    costs={line: revenue * mix[line] / 100 for line in rules.COST_LINES})


def test_cm_formulas():
    day = evaluate_day(make_day(), TARGETS)
    assert day.cm1_pct == 68.0                      # 100 - 26 - 6
    assert day.cm2_pct == 23.0                      # 68 - 11 - 16.5 - 6.5 - 11
    assert day.cm1 == 68_000 and day.cm2 == 23_000


@pytest.mark.parametrize("cm2, colour", [
    (11.99, Colour.RED), (12.0, Colour.YELLOW), (14.95, Colour.YELLOW), (15.0, Colour.GREEN),
    (30.0, Colour.GREEN), (31.0, Colour.YELLOW), (33.0, Colour.YELLOW), (33.01, Colour.BLUE),
])
def test_colour_bands_including_gaps(cm2, colour):
    assert colour_for(cm2) == colour


def test_clean_day():
    day = evaluate_day(make_day(), TARGETS)
    assert day.colour == Colour.GREEN and day.is_clean and scenario_of(day) == "clean day"


def test_line_item_only_breach():
    day = evaluate_day(make_day(**{"Power_&_Fuel": 13}), TARGETS)
    assert scenario_of(day) == "line-item-only breach"
    [anomaly] = day.anomalies
    assert (anomaly.line_item, anomaly.status, anomaly.severity) == ("Power & Fuel", "Above max", Severity.LOW)
    assert anomaly.impact_rupees == 1_000           # 1 pt of ₹1,00,000


def test_cm2_breach_is_red_and_ranked_by_rupee_impact():
    day = evaluate_day(make_day(Manpower=32, Overheads=13, **{"Power_&_Fuel": 16}), TARGETS)
    assert day.colour == Colour.RED and scenario_of(day) == "CM2 breach"
    assert day.anomalies[0].line_item == "CM2 %"    # high severity first
    costs = [a.line_item for a in day.anomalies if a.status == "Above max"]
    assert costs == ["Manpower", "Power & Fuel", "Overheads"]   # 5 pts, 4 pts, 1 pt


def test_suspiciously_high_cm2_is_blue():
    day = evaluate_day(make_day(FC_Rent=2), TARGETS)
    assert day.colour == Colour.BLUE and scenario_of(day) == "suspiciously high CM2"
    insight, action = write_insight(day)
    assert "suspiciously high" in insight and "booked" in action


def test_cm1_tolerance_is_three_points():
    inside = evaluate_day(make_day(Manpower=29, Packaging=7), TARGETS)     # CM1 64% -> within 62-73
    outside = evaluate_day(make_day(Manpower=31, Packaging=7.5), TARGETS)  # CM1 61.5% -> flagged
    assert "CM1 %" not in {a.line_item for a in inside.anomalies}
    assert "CM1 %" in {a.line_item for a in outside.anomalies}


def test_insight_matches_brief_example_shape():
    day = evaluate_day(make_day(Manpower=32.8, **{"Power_&_Fuel": 15.2}, Overheads=12.5, FC_Rent=17.9), TARGETS)
    insight, _ = write_insight(day)
    assert insight.startswith("On 27 May 2025, CM2 =")
    assert "Manpower 32.8% (max 27%" in insight and "Power & Fuel 15.2% (max 12%" in insight
    assert "Recommend: cost audit" in insight


def test_value_just_below_limit_is_not_printed_as_the_limit():
    day = evaluate_day(make_day(FC_Rent=14.98), TARGETS)
    assert "14.98% (min 15%)" in write_insight(day)[0]


def test_override_marks_anomaly_as_known():
    override = Override("FC-T", "Power & Fuel", date(2025, 5, 1), date(2025, 5, 31), "new DG set")
    day = evaluate_day(make_day(**{"Power_&_Fuel": 13}), TARGETS, [override])
    assert day.anomalies[0].acknowledged and not day.open_anomalies
