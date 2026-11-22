"""
Reader for the vendor wagesheet (.xlsx / .xlsm / .csv).

Design choices:
  * openpyxl (not pandas) so identifier cells keep their raw type and we can
    detect float/scientific-notation damage done by Excel.
  * Column headers are matched through aliases (case_study_2/rules.py), so vendors
    may write "UAN No." or "EPF (12%)" instead of the template names.
  * The header row is searched in the first rows, because vendors often add
    a title line above the table.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Optional

import openpyxl

from app.case_study_2 import rules
from app.shared.errors import InputError
from app.case_study_2.matching.normalize import normalize_identifier, parse_amount
from app.case_study_2.models import WagesheetRow

HEADER_SEARCH_ROWS = 10


def _header_key(text: object) -> str:
    """'ESIC @ 0.75%' -> 'esic075' ; 'UAN No.' -> 'uanno'."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


_ALIAS_LOOKUP: dict[str, str] = {
    _header_key(alias): field
    for field, aliases in rules.WAGESHEET_COLUMN_ALIASES.items()
    for alias in aliases
}


def read_wagesheet(path: str) -> list[WagesheetRow]:
    rows = list(_read_raw_rows(path))
    if not rows:
        raise InputError("The wagesheet is empty.", field="wagesheet")

    header_index, column_map = _locate_header(rows)
    employees: list[WagesheetRow] = []
    for offset, raw in enumerate(rows[header_index + 1:], start=header_index + 2):
        if _is_blank(raw):
            continue
        employees.append(_to_row(raw, column_map, excel_row=offset))

    if not employees:
        raise InputError("The wagesheet has a header row but no employee rows.", field="wagesheet")
    return employees


def _read_raw_rows(path: str) -> Iterable[list]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as handle:
            yield from csv.reader(handle)
        return

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise InputError(
            "The wagesheet could not be opened. Please upload a valid .xlsx or .csv file.",
            field="wagesheet",
        ) from exc
    try:
        sheet = workbook.worksheets[0]  # first sheet holds the wagesheet
        for row in sheet.iter_rows(values_only=True):
            yield list(row)
    finally:
        workbook.close()


def _locate_header(rows: list[list]) -> tuple[int, dict[str, int]]:
    """Find the header row and map our field names to column indexes."""
    best_index, best_map = -1, {}
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        column_map: dict[str, int] = {}
        for col, cell in enumerate(row):
            field = _ALIAS_LOOKUP.get(_header_key(cell))
            if field and field not in column_map:
                column_map[field] = col
        if len(column_map) > len(best_map):
            best_index, best_map = index, column_map

    missing = [f for f in rules.REQUIRED_WAGESHEET_COLUMNS if f not in best_map]
    has_identifier = any(f in best_map for f in rules.IDENTIFIER_WAGESHEET_COLUMNS)
    if missing or not has_identifier:
        needed = missing + ([] if has_identifier else ["uan or ip_number"])
        accepted = "; ".join(
            f"{field}: {', '.join(rules.WAGESHEET_COLUMN_ALIASES[field][:3])}"
            for field in needed if field in rules.WAGESHEET_COLUMN_ALIASES
        )
        raise InputError(
            f"The wagesheet is missing required column(s): {', '.join(needed)}. "
            f"Accepted header names include - {accepted or 'UAN / IP Number'}.",
            field="wagesheet",
        )
    return best_index, best_map


def _to_row(raw: list, column_map: dict[str, int], excel_row: int) -> WagesheetRow:
    def cell(field: str) -> Optional[object]:
        index = column_map.get(field)
        if index is None or index >= len(raw):
            return None
        value = raw[index]
        return value.strip() if isinstance(value, str) else value

    uan = normalize_identifier(cell("uan"), rules.UAN_LENGTH, "UAN")
    ip = normalize_identifier(cell("ip_number"), rules.IP_NUMBER_LENGTH, "IP Number")

    return WagesheetRow(
        row_number=excel_row,
        name=str(cell("name") or "").strip(),
        uan=uan.value,
        ip_number=ip.value,
        uan_issue=uan.issue if "uan" in column_map else "UAN column not present in wagesheet",
        ip_issue=ip.issue if "ip_number" in column_map else "IP Number column not present in wagesheet",
        pf_amount=parse_amount(cell("pf_amount")),
        esic_amount=parse_amount(cell("esic_amount")),
        agency=str(cell("agency") or ""),
        state=str(cell("state") or ""),
    )


def _is_blank(row: list) -> bool:
    return all(v is None or str(v).strip() == "" for v in row)
