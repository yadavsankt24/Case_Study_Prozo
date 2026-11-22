"""
Read daily FC cost & revenue data (CSV / Excel) and the target ranges.

Accepted layouts
    1. The sample workbook: a "Day Wise PnL" sheet (Day, Revenue, 6 cost lines)
       plus an "Ideal FC Criteria" sheet with ranges like "25 - 27%".
       It has no FC name or dates, so the FC name comes from the upload form
       and Day N becomes start_date + (N - 1).
    2. A multi-FC file: columns Date, FC, Revenue and the 6 cost lines
       (one row per FC per day). Sheet / column order does not matter.

Rows that cannot be used (zero revenue, text in a number column, negative
costs, duplicates) are skipped with a warning instead of failing the run.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import openpyxl

from app.shared.errors import InputError
from app.case_study_3 import rules
from app.case_study_3.models import DayInput, IngestResult

HEADER_SEARCH_ROWS = 15
FC_ALIASES = {"fc", "fc name", "fc code", "fulfilment centre", "fulfillment center", "centre", "center", "warehouse", "site"}
DATE_ALIASES = {"date", "day date", "business date"}
DAY_ALIASES = {"day", "day no", "day number"}
REVENUE_ALIASES = {"revenue", "total revenue", "net revenue"}
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%m/%d/%Y")


def read_fc_data(path: str, default_fc: str = "FC-01", start_date: Optional[str] = None) -> IngestResult:
    sheets = list(_read_sheets(path))
    if not any(rows for _, rows in sheets):
        raise InputError("The uploaded file is empty.", field="data_file")

    data_sheet = None
    targets, targets_source = dict(rules.DEFAULT_TARGETS), "defaults"
    for name, rows in sheets:
        found_targets = _find_targets(rows)
        if found_targets:
            targets, targets_source = {**targets, **found_targets}, "file"
            continue
        header = _find_data_header(rows)
        if header and data_sheet is None:
            data_sheet = (name, rows, header)

    if data_sheet is None:
        raise InputError(
            "Could not find the daily P&L table. The file needs a header row with Revenue and the cost lines: "
            + ", ".join(rules.COST_LINES) + " (and Day or Date; FC is optional).",
            field="data_file",
        )

    _, rows, (header_index, columns) = data_sheet
    missing = [line for line in rules.COST_LINES if line not in columns]
    if missing:
        raise InputError(f"The data is missing cost column(s): {', '.join(missing)}.", field="data_file")

    first_day = _parse_date(start_date) if start_date else _parse_date(rules.DEFAULT_START_DATE)
    if start_date and first_day is None:
        raise InputError(f"Start date '{start_date}' is not a valid date (use YYYY-MM-DD).", field="start_date")

    inputs, warnings = _rows_to_inputs(rows, header_index, columns, default_fc.strip() or "FC-01", first_day)
    if not inputs:
        raise InputError("No usable rows were found in the file. " + " ".join(warnings[:3]), field="data_file")
    return IngestResult(rows=inputs, targets=targets, targets_source=targets_source, warnings=warnings)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_sheets(path: str) -> Iterable[tuple[str, list[list]]]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as handle:
            yield "csv", [row for row in csv.reader(handle)]
        return
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise InputError("The file could not be opened. Please upload a valid .xlsx or .csv file.",
                         field="data_file") from exc
    try:
        for sheet in workbook.worksheets:
            yield sheet.title, [list(r) for r in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _key(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]", " ", str(value or "").lower())).strip()


def _find_data_header(rows: list[list]) -> Optional[tuple[int, dict[str, int]]]:
    """Return (header row index, {field: column}) if this sheet holds the daily P&L table."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns: dict[str, int] = {}
        for col, cell in enumerate(row):
            key = _key(cell)
            if key in REVENUE_ALIASES:
                columns.setdefault("revenue", col)
            elif key in FC_ALIASES:
                columns.setdefault("fc", col)
            elif key in DATE_ALIASES:
                columns.setdefault("date", col)
            elif key in DAY_ALIASES:
                columns.setdefault("day", col)
            elif key in rules.LINE_ALIASES:
                columns.setdefault(rules.LINE_ALIASES[key], col)
        cost_columns = [line for line in rules.COST_LINES if line in columns]
        if "revenue" in columns and len(cost_columns) >= 3:
            return index, columns
    return None


def _find_targets(rows: list[list]) -> dict[str, tuple[float, float]]:
    """Read an 'Expense Line Item | Range (as % of Revenue)' sheet, if this is one."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        keys = [_key(c) for c in row]
        line_col = next((i for i, k in enumerate(keys) if "line item" in k), None)
        range_col = next((i for i, k in enumerate(keys) if k.startswith("range")), None)
        if line_col is None or range_col is None:
            continue
        targets = {}
        for data_row in rows[index + 1:]:
            if max(line_col, range_col) >= len(data_row):
                continue
            line = rules.LINE_ALIASES.get(_key(data_row[line_col]))
            parsed = parse_range(data_row[range_col])
            if line and parsed:
                targets[line] = parsed
        return targets
    return {}


def parse_range(value: object) -> Optional[tuple[float, float]]:
    """'25 - 27%' -> (25.0, 27.0); also '25%-27%' and '25 to 27'."""
    numbers = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
    if len(numbers) != 2:
        return None
    low, high = float(numbers[0]), float(numbers[1])
    return (low, high) if low <= high else (high, low)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _rows_to_inputs(rows: list[list], header_index: int, columns: dict[str, int], default_fc: str,
                    first_day: date) -> tuple[list[DayInput], list[str]]:
    inputs: dict[tuple[str, date], DayInput] = {}
    warnings: list[str] = []

    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if all(v is None or str(v).strip() == "" for v in row):
            continue

        def cell(field: str) -> object:
            col = columns.get(field)
            return row[col] if col is not None and col < len(row) else None

        fc = str(cell("fc") or default_fc).strip()
        day = _row_date(cell("date"), cell("day"), first_day, len(inputs))
        if day is None:
            warnings.append(f"Row {offset}: date / day '{cell('date') or cell('day')}' not understood - skipped.")
            continue

        revenue = _number(cell("revenue"))
        if revenue is None or revenue <= 0:
            warnings.append(f"Row {offset} ({fc}, {day:%d %b %Y}): revenue is zero, blank or not a number - skipped "
                            f"(percentages cannot be calculated).")
            continue

        costs, problems = {}, []
        for line in rules.COST_LINES:
            value = _number(cell(line))
            if value is None:
                problems.append(f"{line} is blank or not a number")
            elif value < 0:
                problems.append(f"{line} is negative")
            else:
                costs[line] = value
        if problems:
            warnings.append(f"Row {offset} ({fc}, {day:%d %b %Y}): {'; '.join(problems)} - skipped.")
            continue

        key = (fc, day)
        if key in inputs:
            warnings.append(f"Row {offset}: {fc} on {day:%d %b %Y} appears more than once - the later row is used.")
        inputs[key] = DayInput(fc=fc, day=day, revenue=revenue, costs=costs, source_row=offset)

    ordered = sorted(inputs.values(), key=lambda r: (r.fc, r.day))
    return ordered, warnings


def _row_date(date_cell: object, day_cell: object, first_day: date, position: int) -> Optional[date]:
    if date_cell not in (None, ""):
        return _parse_date(date_cell)
    if day_cell not in (None, ""):
        number = _number(day_cell)
        return first_day + timedelta(days=int(number) - 1) if number and number >= 1 else None
    return first_day + timedelta(days=position)


def _parse_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _number(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").replace("₹", "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None
