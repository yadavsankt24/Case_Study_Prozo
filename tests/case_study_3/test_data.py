"""Case Study 3: reading the files, planted scenarios and bad inputs."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from app.shared.errors import InputError
from app.case_study_3.engine import evaluate_day, scenario_of
from app.case_study_3.ingest import parse_range, read_fc_data
from tests.conftest import CS3_DATA as CS3


def test_brief_sample_workbook():
    data = read_fc_data(str(CS3 / "Case Study 3.xlsx"))
    assert len(data.rows) == 100 and data.targets_source == "file"
    assert data.targets["Power & Fuel"] == (10, 12)               # "Power and Fuel" in the file
    assert data.rows[26].day == date(2025, 5, 27)                 # Day 27 -> 27 May (default start)
    days = [evaluate_day(r, data.targets) for r in data.rows]
    colours = {c: sum(1 for d in days if d.colour.value == c) for c in ("Red", "Yellow", "Green", "Blue")}
    assert colours == {"Red": 3, "Yellow": 11, "Green": 86, "Blue": 0}


def test_custom_fc_name_and_start_date():
    data = read_fc_data(str(CS3 / "Case Study 3.xlsx"), default_fc="FC-Noida", start_date="2025-01-01")
    assert data.rows[0].fc == "FC-Noida" and data.rows[0].day == date(2025, 1, 1)


def test_planted_scenarios_are_all_detected():
    data = read_fc_data(str(CS3 / "multi_fc_may_2025.csv"))
    days = {(d.fc, d.day.isoformat()): evaluate_day(d, data.targets) for d in data.rows}
    with open(CS3 / "expected_scenarios.csv", newline="") as handle:
        expected = list(csv.DictReader(handle))
    assert len(days) == len(expected) == 124
    wrong = [e for e in expected
             if days[(e["fc"], e["date"])].colour.value != e["expected_colour"]
             or (e["expected_scenario"] and scenario_of(days[(e["fc"], e["date"])]) != e["expected_scenario"])]
    assert not wrong
    found = {scenario_of(d) for d in days.values()}
    assert {"clean day", "CM2 breach", "line-item-only breach", "suspiciously high CM2"} <= found


@pytest.mark.parametrize("value, expected", [("25 - 27%", (25, 27)), ("5%-7%", (5, 7)), ("10 to 12", (10, 12)),
                                             ("n/a", None)])
def test_parse_range(value, expected):
    assert parse_range(value) == expected


@pytest.mark.parametrize("name, message", [
    ("header_only.csv", "No usable rows"),
    ("missing_overheads_column.csv", "missing cost column"),
    ("not_a_pnl_file.csv", "Could not find the daily P&L table"),
])
def test_bad_files_give_clear_messages(name, message):
    with pytest.raises(InputError, match=message):
        read_fc_data(str(CS3 / "bad_inputs" / name))


def test_bad_rows_are_skipped_with_warnings():
    data = read_fc_data(str(CS3 / "bad_inputs" / "some_bad_rows.csv"))
    assert len(data.rows) == 2
    text = " ".join(data.warnings)
    assert "revenue is zero" in text and "not a number" in text and "negative" in text and "not understood" in text
