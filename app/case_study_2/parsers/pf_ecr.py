"""
Parser for the EPFO PF ECR (Electronic Challan cum Return) PDF.

Reads:
  * header details (establishment, wage month, printed totals) from page 1
  * every member row: UAN, both names, wages, EE / EPS / ER shares, NCP days
"""

from __future__ import annotations

import re
from typing import Optional

from app.case_study_2.rules import UAN_LENGTH
from app.case_study_2.matching.normalize import parse_amount
from app.case_study_2.models import ParseLog, PfEcrDocument, PfEcrMember
from app.case_study_2.parsers.pdf_table import ColumnSpec, ProgressCallback, TableSpec, open_pdf, read_table

PF_TABLE = TableSpec(
    columns=[
        ColumnSpec("sl_no", ("Sl.", "No.")),
        ColumnSpec("uan", ("UAN",)),
        ColumnSpec("name_ecr", ("Name", "as", "per", "ECR")),
        ColumnSpec("name_uan_repository", ("UAN", "Repository"), optional=True),
        ColumnSpec("gross_wages", ("Wages",)),
        ColumnSpec("epf_wages", ("Wages",)),
        ColumnSpec("eps_wages", ("Wages",)),
        ColumnSpec("edli_wages", ("Wages",)),
        ColumnSpec("ee_share", ("EE",)),
        ColumnSpec("eps_share", ("EPS",)),
        ColumnSpec("er_share", ("ER",)),
        ColumnSpec("ncp_days", ("Days",), optional=True),
    ],
    id_column="uan",
    id_pattern=re.compile(rf"\d{{{UAN_LENGTH}}}"),
    wrap_columns=("name_ecr", "name_uan_repository"),
    header_keywords={"uan", "ee", "er"},
)

_HEADER_PATTERNS = {
    "establishment_name": r"Name of Establishment\s+(.+)",
    "establishment_id": r"Establishment Id\s+(\S+)",
    "wage_month": r"Wage Month\s+([A-Z]{3}-\d{4})",
    "return_month": r"Return Month\s+([A-Z]{3}-\d{4})",
    "total_members": r"Total Members\s+([\d,]+)",
    "total_epf_contribution": r"Total EPF Contribution\s+([\d,]+)",
    "total_eps_contribution": r"Total EPS Contribution\s+([\d,]+)",
}

_NUMERIC_FIELDS = (
    "gross_wages", "epf_wages", "eps_wages", "edli_wages",
    "ee_share", "eps_share", "er_share", "ncp_days",
)


def looks_like_pf_ecr(first_page_text: str) -> bool:
    text = first_page_text.upper()
    return "PROVIDENT FUND" in text or ("UAN" in text and " EE " in f" {text} ")


def parse_pf_ecr(path: str, on_page: Optional[ProgressCallback] = None) -> PfEcrDocument:
    log = ParseLog()
    with open_pdf(path, "PF ECR") as pdf:
        header = _read_header(pdf.pages[0].extract_text() or "")
        members = [_to_member(row.cells, row.page, log) for row in read_table(pdf, PF_TABLE, log, on_page)]
    return PfEcrDocument(members=members, header=header, log=log)


def _read_header(text: str) -> dict:
    header: dict = {}
    for key, pattern in _HEADER_PATTERNS.items():
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1).strip()
        if key == "establishment_name":
            # the same visual line also holds other labels in some layouts
            value = re.split(r"\s{2,}|Establishment Id", value)[0].strip()
        header[key] = parse_amount(value) if key.startswith("total_") else value
    return header


def _to_member(cells: dict[str, str], page: int, log: ParseLog) -> PfEcrMember:
    values: dict[str, Optional[float]] = {}
    for field_name in _NUMERIC_FIELDS:
        raw = cells.get(field_name)
        values[field_name] = parse_amount(raw)
        if raw and values[field_name] is None:
            log.value_errors.append(f"p{page} UAN {cells.get('uan')}: could not read {field_name} '{raw}'")

    return PfEcrMember(
        uan=cells["uan"].strip(),
        name_ecr=cells.get("name_ecr", "").strip(),
        name_uan_repository=cells.get("name_uan_repository", "").strip(),
        page=page,
        **values,
    )
