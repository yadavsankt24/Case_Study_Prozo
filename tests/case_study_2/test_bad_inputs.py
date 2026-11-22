"""Bad input must give a clear message, never a crash."""

from __future__ import annotations

import pytest

from app.shared.errors import InputError
from app.case_study_2.pipeline import VerificationPipeline
from app.case_study_2.validation import check_upload
from tests.conftest import SAMPLE_ESIC, SAMPLE_PF, SAMPLE_WAGESHEET


@pytest.mark.parametrize("pf_file, message", [
    ("corrupt_pf_ecr.pdf", "could not be opened"),
    ("renamed_excel_as_pdf.pdf", "not a real PDF"),
    ("scanned_pf_ecr.pdf", "scanned image"),
    ("not_an_ecr_invoice.pdf", "does not look like an EPFO ECR"),
])
def test_bad_pf_ecr(synthetic_data, pf_file, message):
    with pytest.raises(InputError, match=message):
        VerificationPipeline().run(str(SAMPLE_WAGESHEET), str(synthetic_data / "bad_inputs" / pf_file),
                                   str(SAMPLE_ESIC))


def test_files_in_the_wrong_boxes():
    with pytest.raises(InputError, match="looks like an ESIC ECR"):
        VerificationPipeline().run(str(SAMPLE_WAGESHEET), str(SAMPLE_ESIC), str(SAMPLE_ESIC))


@pytest.mark.parametrize("wagesheet_file, message", [
    ("wagesheet_wrong_columns.xlsx", "missing required column"),
    ("wagesheet_header_only.xlsx", "no employee rows"),
])
def test_bad_wagesheet(synthetic_data, wagesheet_file, message):
    with pytest.raises(InputError, match=message):
        VerificationPipeline().run(str(synthetic_data / "bad_inputs" / wagesheet_file), str(SAMPLE_PF),
                                   str(SAMPLE_ESIC))


@pytest.mark.parametrize("slot, filename, size, message", [
    ("wagesheet", "wages.txt", 10, "must be one of"),
    ("pf_ecr", "pf.pdf", 0, "empty"),
    ("esic_ecr", "", 10, "choose a file"),
])
def test_upload_checks(slot, filename, size, message):
    with pytest.raises(InputError, match=message):
        check_upload(slot, filename, size, max_mb=50)
