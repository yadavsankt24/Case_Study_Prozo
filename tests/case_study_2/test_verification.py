"""End-to-end verification against answer keys."""

from __future__ import annotations

import csv

import pytest

from app.case_study_2.models import Status
from app.case_study_2.pipeline import VerificationPipeline
from tests.conftest import SAMPLE, SAMPLE_ESIC, SAMPLE_PF, SAMPLE_WAGESHEET


def _expected(folder):
    with open(folder / "expected_results.csv", newline="") as handle:
        return {int(r["row_number"]): r for r in csv.DictReader(handle)}


def test_sample_answer_key_exactly():
    report = VerificationPipeline().run(str(SAMPLE_WAGESHEET), str(SAMPLE_PF), str(SAMPLE_ESIC))
    expected = _expected(SAMPLE)
    for emp in report.employees:
        row = expected[emp.row.row_number]
        assert emp.pf.status.value == row["expected_pf_status"], emp.row.name
        assert emp.esic.status.value == row["expected_esic_status"], emp.row.name

    summary = report.summary()
    assert summary["pf"]["counts"] == {"Matched": 9, "Name mismatch": 1, "Amount mismatch": 1, "Missing": 1}
    assert summary["esic"]["counts"] == {"Matched": 8, "Name mismatch": 1, "Amount mismatch": 1, "Missing": 2}
    assert summary["reconciliation_ok"]


def test_amount_mismatch_shows_values_and_cross_check():
    report = VerificationPipeline().run(str(SAMPLE_WAGESHEET), str(SAMPLE_PF), str(SAMPLE_ESIC))
    vikram = next(e for e in report.employees if e.row.name == "VIKRAM THAKUR")
    assert vikram.pf.status == Status.AMOUNT_MISMATCH
    assert (vikram.pf.wagesheet_amount, vikram.pf.ecr_amount, vikram.pf.difference) == (1654, 1354, -300)
    assert "ECR deposit is wrong" in vikram.pf.reason


@pytest.mark.parametrize("set_name", ["set_01_name_variants", "set_02_messy_vendor_file", "set_03_large_scale"])
def test_synthetic_sets_match_answer_key(synthetic_data, set_name):
    folder = synthetic_data / set_name
    report = VerificationPipeline().run(str(folder / "wagesheet.xlsx"), str(folder / "pf_ecr.pdf"),
                                        str(folder / "esic_ecr.pdf"))
    expected = _expected(folder)
    wrong = [
        (emp.row.row_number, check, got.status.value, want)
        for emp in report.employees
        for check, got, want in (("PF", emp.pf, expected[emp.row.row_number]["expected_pf_status"]),
                                 ("ESIC", emp.esic, expected[emp.row.row_number]["expected_esic_status"]))
        if got.status.value != want
    ]
    assert not wrong, wrong[:10]
    assert all(r.ok for r in report.reconciliation)
