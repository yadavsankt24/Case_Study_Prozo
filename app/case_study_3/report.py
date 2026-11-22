"""
Excel report for one Case Study 3 run.

Sheets
    Summary      FC-days, colour counts, scenario counts, warnings, targets used
    Daily P&L    per FC per day: revenue, each cost %, CM1, CM1 %, CM2, CM2 %, colour
    Anomalies    the required log: Date | FC | Line Item | % of Revenue | Target Range | Status
                 (+ severity, rupee impact, known-issue note)
    Insights     one plain-language insight and recommended action per flagged FC-day
    Dashboard    FC x date grid coloured by status, value = CM2 %
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.case_study_3 import rules
from app.case_study_3.engine import scenario_of
from app.case_study_3.models import DayResult

BRAND = "5B2C91"
HEADER_FONT, HEADER_FILL = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=BRAND)
TITLE_FONT = Font(bold=True, size=14, color=BRAND)
BORDER = Border(*(Side(style="thin", color="DDD6E8"),) * 4)
FILLS = {"Red": "F9D9D9", "Yellow": "FFF4CC", "Green": "E3F4E8", "Blue": "DCEBFB"}
COLOUR_FILLS = {k: PatternFill("solid", fgColor=v) for k, v in FILLS.items()}


def write_report(days: list[DayResult], targets: dict, warnings: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    _summary(wb.active, days, targets, warnings)
    _daily_pnl(wb.create_sheet("Daily P&L"), days)
    _anomalies(wb.create_sheet("Anomalies"), days)
    _insights(wb.create_sheet("Insights"), days)
    _dashboard(wb.create_sheet("Dashboard"), days)
    wb.save(path)
    return path


def _header(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row, col, label)
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _widths(ws, widths: list[int]) -> None:
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _summary(ws, days: list[DayResult], targets: dict, warnings: list[str]) -> None:
    ws.title = "Summary"
    ws["A1"], ws["A1"].font = "Daily FC P&L monitor - summary", TITLE_FONT
    fcs = sorted({d.fc for d in days})
    dates = sorted({d.day for d in days})
    info = [("FCs", ", ".join(fcs)), ("Date range", f"{dates[0]:%d %b %Y} to {dates[-1]:%d %b %Y}"),
            ("FC-days analysed", len(days))]
    for r, (label, value) in enumerate(info, start=3):
        ws.cell(r, 1, label).font = Font(bold=True)
        ws.cell(r, 2, value)

    row = 7
    _header(ws, row, ["Colour", "FC-days", "Meaning"])
    meaning = {"Red": f"CM2 below {rules.RED_BELOW:g}%", "Yellow": "CM2 12-14.9% or 30-33%",
               "Green": "CM2 15-30% (healthy)", "Blue": f"CM2 above {rules.BLUE_ABOVE:g}% (check unreported costs)"}
    counts = Counter(d.colour.value for d in days)
    for colour in ("Red", "Yellow", "Green", "Blue"):
        row += 1
        ws.cell(row, 1, colour).fill = COLOUR_FILLS[colour]
        ws.cell(row, 2, counts.get(colour, 0))
        ws.cell(row, 3, meaning[colour])

    row += 2
    _header(ws, row, ["Scenario", "FC-days"])
    for scenario, count in sorted(Counter(scenario_of(d) for d in days).items()):
        row += 1
        ws.cell(row, 1, scenario)
        ws.cell(row, 2, count)

    row += 2
    _header(ws, row, ["Cost line", "Target range (% of revenue)"])
    for line in rules.COST_LINES:
        row += 1
        ws.cell(row, 1, line)
        ws.cell(row, 2, f"{targets[line][0]:g}-{targets[line][1]:g}%")
    for label, (low, high) in (("CM1 %", rules.CM1_TARGET), ("CM2 %", rules.CM2_TARGET)):
        row += 1
        ws.cell(row, 1, label)
        ws.cell(row, 2, f"{low:g}-{high:g}% (flag beyond ±{rules.CM_TOLERANCE_PTS:g} pts)")

    row += 2
    ws.cell(row, 1, "Warnings").font = TITLE_FONT
    for warning in warnings or ["None"]:
        row += 1
        ws.cell(row, 1, warning)
    _widths(ws, [30, 34, 40])


def _daily_pnl(ws, days: list[DayResult]) -> None:
    headers = (["Date", "FC", "Revenue"] + [f"{line} %" for line in rules.COST_LINES]
               + ["CM1", "CM1 %", "CM2", "CM2 %", "Colour", "Flags"])
    _header(ws, 1, headers)
    for r, d in enumerate(days, start=2):
        values = ([d.day, d.fc, d.revenue] + [d.pct[line] for line in rules.COST_LINES]
                  + [d.cm1, d.cm1_pct, d.cm2, d.cm2_pct, d.colour.value, len(d.anomalies)])
        for c, value in enumerate(values, start=1):
            cell = ws.cell(r, c, value)
            cell.border = BORDER
            if c == 1:
                cell.number_format = "DD-MMM-YYYY"
        ws.cell(r, 14).fill = COLOUR_FILLS[d.colour.value]
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(days) + 1}"
    _widths(ws, [13, 14, 11] + [12] * 6 + [11, 8, 11, 8, 9, 7])


def _anomalies(ws, days: list[DayResult]) -> None:
    headers = ["Date", "FC", "Line Item", "% of Revenue", "Target Range", "Status", "Severity",
               "Impact (₹)", "Day colour", "Note"]
    _header(ws, 1, headers)
    r = 1
    for d in days:
        for a in d.anomalies:
            r += 1
            values = [a.day, a.fc, a.line_item, a.pct_of_revenue, a.target_range, a.status, a.severity.value,
                      a.impact_rupees or None, d.colour.value, a.note]
            for c, value in enumerate(values, start=1):
                cell = ws.cell(r, c, value)
                cell.border = BORDER
                if c == 1:
                    cell.number_format = "DD-MMM-YYYY"
            ws.cell(r, 9).fill = COLOUR_FILLS[d.colour.value]
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:J{max(r, 1)}"
    _widths(ws, [13, 14, 18, 12, 30, 13, 10, 11, 10, 40])


def _insights(ws, days: list[DayResult]) -> None:
    _header(ws, 1, ["Date", "FC", "Colour", "Insight", "Recommended action"])
    r = 1
    for d in days:
        if d.is_clean:
            continue
        r += 1
        for c, value in enumerate([d.day, d.fc, d.colour.value, d.insight, d.action], start=1):
            cell = ws.cell(r, c, value)
            cell.border, cell.alignment = BORDER, Alignment(wrap_text=True, vertical="top")
            if c == 1:
                cell.number_format = "DD-MMM-YYYY"
        ws.cell(r, 3).fill = COLOUR_FILLS[d.colour.value]
    ws.freeze_panes = "D2"
    _widths(ws, [13, 14, 9, 110, 50])


def _dashboard(ws, days: list[DayResult]) -> None:
    fcs = sorted({d.fc for d in days})
    dates = sorted({d.day for d in days})
    by_key = {(d.fc, d.day): d for d in days}
    ws["A1"], ws["A1"].font = "Daily status (cell value = CM2 %)", TITLE_FONT
    ws.cell(3, 1, "FC").font = Font(bold=True)
    for c, day in enumerate(dates, start=2):
        cell = ws.cell(3, c, day.strftime("%d-%b"))
        cell.font, cell.alignment = Font(bold=True, size=9), Alignment(text_rotation=90)
        ws.column_dimensions[get_column_letter(c)].width = 5.5
    for r, fc in enumerate(fcs, start=4):
        ws.cell(r, 1, fc).font = Font(bold=True)
        for c, day in enumerate(dates, start=2):
            d = by_key.get((fc, day))
            if d:
                cell = ws.cell(r, c, round(d.cm2_pct, 1))
                cell.fill, cell.font = COLOUR_FILLS[d.colour.value], Font(size=8)
    ws.column_dimensions["A"].width = 16
    ws.freeze_panes = "B4"
