"""
Input validation: catch bad uploads early and explain them in plain language.

Two levels:
  * `check_upload()`  - cheap checks done in the API request (extension, empty file)
  * `validate_inputs()` - deeper checks done in the background job before parsing
                         (file opens, has a text layer, is the right document type)
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from app.shared.errors import InputError
from app.case_study_2.parsers.esic_ecr import looks_like_esic_ecr
from app.case_study_2.parsers.pf_ecr import looks_like_pf_ecr

WAGESHEET_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}
PDF_EXTENSIONS = {".pdf"}

SLOT_LABELS = {"wagesheet": "wagesheet", "pf_ecr": "PF ECR", "esic_ecr": "ESIC ECR"}


def check_upload(slot: str, filename: str, size_bytes: int, max_mb: int) -> None:
    label = SLOT_LABELS[slot]
    if not filename:
        raise InputError(f"Please choose a file for the {label}.", field=slot)
    suffix = Path(filename).suffix.lower()
    allowed = WAGESHEET_EXTENSIONS if slot == "wagesheet" else PDF_EXTENSIONS
    if suffix not in allowed:
        raise InputError(
            f"The {label} must be one of {', '.join(sorted(allowed))} (got '{suffix or 'no extension'}').",
            field=slot,
        )
    if size_bytes == 0:
        raise InputError(f"The {label} file is empty.", field=slot)
    if size_bytes > max_mb * 1024 * 1024:
        raise InputError(f"The {label} is larger than {max_mb} MB.", field=slot)


def validate_inputs(wagesheet_path: str, pf_path: str, esic_path: str) -> None:
    _validate_pdf(pf_path, "pf_ecr")
    _validate_pdf(esic_path, "esic_ecr")
    # The wagesheet is validated while it is read (header/columns), see parsers/wagesheet.py


def _validate_pdf(path: str, slot: str) -> None:
    label = SLOT_LABELS[slot]
    with open(path, "rb") as handle:
        if not handle.read(5).startswith(b"%PDF"):
            raise InputError(f"The {label} is not a real PDF file (it may be renamed or corrupt).", field=slot)

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise InputError(f"The {label} has no pages.", field=slot)
            first_text = pdf.pages[0].extract_text() or ""
    except InputError:
        raise
    except Exception as exc:
        raise InputError(
            f"The {label} could not be opened. It may be corrupt or password-protected.", field=slot
        ) from exc

    if len(first_text.strip()) < 20:
        raise InputError(
            f"The {label} looks like a scanned image (no readable text). "
            f"Please download the text-based ECR from the portal.",
            field=slot,
        )

    is_pf, is_esic = looks_like_pf_ecr(first_text), looks_like_esic_ecr(first_text)
    if slot == "pf_ecr" and not is_pf:
        hint = " It looks like an ESIC ECR - check that the files are in the right boxes." if is_esic else ""
        raise InputError(f"The file uploaded as PF ECR does not look like an EPFO ECR.{hint}", field=slot)
    if slot == "esic_ecr" and not is_esic:
        hint = " It looks like a PF ECR - check that the files are in the right boxes." if is_pf else ""
        raise InputError(f"The file uploaded as ESIC ECR does not look like an ESIC contribution history.{hint}",
                         field=slot)
