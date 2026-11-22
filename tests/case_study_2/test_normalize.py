from __future__ import annotations

import pytest

from app.case_study_2.matching.amounts import round_nearest, round_up
from app.case_study_2.matching.normalize import normalize_identifier, parse_amount


@pytest.mark.parametrize("raw, expected", [
    ("999912340001", "999912340001"),
    (999912340001, "999912340001"),          # Excel number
    (999912340001.0, "999912340001"),        # Excel float
    ("999912340001.0", "999912340001"),
    ("9999 1234 0001", "999912340001"),      # typed with spaces
])
def test_valid_uan_forms(raw, expected):
    assert normalize_identifier(raw, 12, "UAN").value == expected


@pytest.mark.parametrize("raw, issue_word", [
    (None, "blank"),
    ("", "blank"),
    ("9.99912E+11", "scientific"),           # digits destroyed by Excel
    ("99991234", "8 digits"),
    ("UAN-PENDING", "non-numeric"),
])
def test_unusable_uan_explains_why(raw, issue_word):
    result = normalize_identifier(raw, 12, "UAN")
    assert result.value is None
    assert issue_word in result.issue


def test_parse_amount():
    assert parse_amount("1,622") == 1622
    assert parse_amount("102.00") == 102
    assert parse_amount("-") is None
    assert parse_amount(None) is None


def test_statutory_rounding():
    assert round_up(13520 * 0.0075) == 102      # ESIC: 101.40 -> 102
    assert round_nearest(13780 * 0.12) == 1654  # PF: 1653.6 -> 1654
    assert round_nearest(12.5) == 13            # half goes up, unlike Python's round()
