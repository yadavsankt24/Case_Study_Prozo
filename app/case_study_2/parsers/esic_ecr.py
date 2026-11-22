"""
Parser for the ESIC contribution history (ECR) PDF.

Reads:
  * header totals (printed as a row of labels with values underneath)
  * every insured-person row: IP number, name, days, wages, IP contribution, reason
"""

from __future__ import annotations

import re
from typing import Optional

from app.case_study_2.rules import IP_NUMBER_LENGTH
from app.case_study_2.matching.normalize import parse_amount
from app.case_study_2.models import EsicEcrDocument, EsicEcrMember, ParseLog
from app.case_study_2.parsers.pdf_table import (
    ColumnSpec,
    ProgressCallback,
    TableSpec,
    open_pdf,
    page_lines,
    read_table,
    value_below_label,
)

ESIC_TABLE = TableSpec(
    columns=[
        ColumnSpec("sno", ("SNo.",), optional=True),
        ColumnSpec("is_disable", ("Is", "Disable"), optional=True),
        ColumnSpec("ip_number", ("IP", "Number")),
        ColumnSpec("name", ("IP", "Name")),
        ColumnSpec("days", ("No.", "Of", "Days")),
        ColumnSpec("wages", ("Total", "Wages")),
        ColumnSpec("ip_contribution", ("IP", "Contribution")),
        ColumnSpec("reason", ("Reason",), optional=True),
    ],
    id_column="ip_number",
    id_pattern=re.compile(rf"\d{{{IP_NUMBER_LENGTH}}}"),
    wrap_columns=("name",),
    header_keywords={"ip", "number", "contribution"},
)

_HEADER_TOTALS = {
    "total_ip_contribution": ("Total", "IP", "Contribution"),
    "total_employer_contribution": ("Total", "Employer", "Contribution"),
    "total_monthly_wages": ("Total", "Monthly", "Wages"),
}


def looks_like_esic_ecr(first_page_text: str) -> bool:
    text = first_page_text.upper()
    return "STATE INSURANCE" in text or "IP NUMBER" in text or "IP CONTRIBUTION" in text


def parse_esic_ecr(path: str, on_page: Optional[ProgressCallback] = None) -> EsicEcrDocument:
    log = ParseLog()
    with open_pdf(path, "ESIC ECR") as pdf:
        header = _read_header(pdf.pages[0])
        members = [_to_member(row.cells, row.page, log) for row in read_table(pdf, ESIC_TABLE, log, on_page)]
    return EsicEcrDocument(members=members, header=header, log=log)


def _read_header(page) -> dict:
    lines = page_lines(page)
    header: dict = {}
    for key, label in _HEADER_TOTALS.items():
        value = parse_amount(value_below_label(lines, label))
        if value is not None:
            header[key] = value

    text = page.extract_text() or ""
    month = re.search(r"for\s+([A-Za-z]{3})[\s\-]*(\d{4})", text)
    if month:
        header["wage_month"] = f"{month.group(1).upper()}-{month.group(2)}"
    employer_code = re.search(r"Contribution History Of\s+(\d+)", text)
    if employer_code:
        header["employer_code"] = employer_code.group(1)
    return header


def _to_member(cells: dict[str, str], page: int, log: ParseLog) -> EsicEcrMember:
    values: dict[str, Optional[float]] = {}
    for field_name in ("days", "wages", "ip_contribution"):
        raw = cells.get(field_name)
        values[field_name] = parse_amount(raw)
        if raw and values[field_name] is None:
            log.value_errors.append(f"p{page} IP {cells.get('ip_number')}: could not read {field_name} '{raw}'")

    return EsicEcrMember(
        ip_number=cells["ip_number"].strip(),
        name=cells.get("name", "").strip(),
        reason=cells.get("reason", "").strip(),
        page=page,
        **values,
    )
