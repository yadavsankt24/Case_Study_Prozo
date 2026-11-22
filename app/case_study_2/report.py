"""
Excel report writer.

Sheets:
    Summary        counts per status (PF / ESIC), money short-deposited, reconciliation, warnings
    PF Results     one row per employee, PF verdict with both values and the reason
    ESIC Results   same for ESIC
    Combined       PF and ESIC side by side, with an "Action needed" column
    ECR Only       members filed by the vendor who are not on the wagesheet
    Parse Log      what the PDF parser read, so nothing is dropped silently
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.case_study_2.models import CheckResult, EmployeeResult, Status, VerificationReport

BRAND = "5B2C91"
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=BRAND)
TITLE_FONT = Font(bold=True, size=14, color=BRAND)
THIN = Side(style="thin", color="D9D2E9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

STATUS_FILLS = {
    Status.MATCHED.value: PatternFill("solid", fgColor="E3F4E8"),
    Status.NAME_MISMATCH.value: PatternFill("solid", fgColor="FDEBD3"),
    Status.AMOUNT_MISMATCH.value: PatternFill("solid", fgColor="FFF4CC"),
    Status.MISSING.value: PatternFill("solid", fgColor="F9D9D9"),
}


class ExcelReportWriter:
    def write(self, report: VerificationReport, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        self._summary_sheet(workbook.active, report)
        self._check_sheet(workbook.create_sheet("PF Results"), report.employees, "pf", "UAN", "PF @ 12%", "ECR EE share")
        self._check_sheet(workbook.create_sheet("ESIC Results"), report.employees, "esic", "IP Number",
                          "ESIC @ 0.75%", "ECR IP contribution")
        self._combined_sheet(workbook.create_sheet("Combined"), report.employees)
        self._ecr_only_sheet(workbook.create_sheet("ECR Only"), report)
        self._parse_log_sheet(workbook.create_sheet("Parse Log"), report)
        workbook.save(path)
        return path

    # ------------------------------------------------------------------ #

    def _summary_sheet(self, ws: Worksheet, report: VerificationReport) -> None:
        ws.title = "Summary"
        summary = report.summary()
        meta = report.metadata
        pf_header, esic_header = meta.get("pf_header", {}), meta.get("esic_header", {})

        ws["A1"] = "Wagesheet vs PF / ESIC ECR - Verification Summary"
        ws["A1"].font = TITLE_FONT
        info = [
            ("Establishment", pf_header.get("establishment_name", "")),
            ("Wage month", pf_header.get("wage_month") or esic_header.get("wage_month", "")),
            ("Wagesheet", meta["files"]["wagesheet"]),
            ("PF ECR", meta["files"]["pf_ecr"]),
            ("ESIC ECR", meta["files"]["esic_ecr"]),
            ("Employees in wagesheet", summary["total_employees"]),
            ("Amount tolerance (₹)", meta.get("amount_tolerance")),
            ("Generated at (UTC)", meta.get("generated_at")),
        ]
        for offset, (label, value) in enumerate(info, start=3):
            ws.cell(offset, 1, label).font = Font(bold=True)
            ws.cell(offset, 2, value)

        row = len(info) + 4
        self._header(ws, row, ["Status", "PF", "ESIC"])
        for status in Status:
            row += 1
            ws.cell(row, 1, status.value).fill = STATUS_FILLS[status.value]
            ws.cell(row, 2, summary["pf"]["counts"][status.value])
            ws.cell(row, 3, summary["esic"]["counts"][status.value])
        extra_rows = [
            ("Total", summary["pf"]["total"], summary["esic"]["total"]),
            ("Matched but needs review", summary["pf"]["needs_review"], summary["esic"]["needs_review"]),
            ("Match rate %", summary["pf"]["match_rate"], summary["esic"]["match_rate"]),
            ("Short-deposited amount (₹)", summary["pf"]["short_deposit_amount"],
             summary["esic"]["short_deposit_amount"]),
            ("In ECR but not in wagesheet", summary["ecr_only"]["pf"], summary["ecr_only"]["esic"]),
        ]
        for label, pf_value, esic_value in extra_rows:
            row += 1
            ws.cell(row, 1, label).font = Font(bold=True)
            ws.cell(row, 2, pf_value)
            ws.cell(row, 3, esic_value)

        row += 2
        ws.cell(row, 1, "Totals reconciliation (parsed vs printed on ECR)").font = TITLE_FONT
        row += 1
        self._header(ws, row, ["Document", "Metric", "Printed", "Parsed", "Result"])
        for check in report.reconciliation:
            row += 1
            values = [check.document, check.metric, check.printed_value, check.parsed_value,
                      "OK" if check.ok else f"CHECK: {check.note}"]
            for col, value in enumerate(values, start=1):
                ws.cell(row, col, value).border = BORDER

        row += 2
        ws.cell(row, 1, "Warnings").font = TITLE_FONT
        for warning in report.warnings or ["None"]:
            row += 1
            ws.cell(row, 1, warning)

        self._widths(ws, [34, 30, 14, 14, 50])

    def _check_sheet(self, ws: Worksheet, employees: list[EmployeeResult], attr: str,
                     id_label: str, ws_amount_label: str, ecr_amount_label: str) -> None:
        headers = ["Row", "Employee name", "Agency", "State", id_label, "ECR name",
                   f"Wagesheet {ws_amount_label}", ecr_amount_label, "Difference (ECR - wagesheet)",
                   "Status", "Needs review", "Reason", "ECR page"]
        self._header(ws, 1, headers)
        for index, emp in enumerate(employees, start=2):
            result: CheckResult = getattr(emp, attr)
            identifier = result.identifier or (emp.row.uan if attr == "pf" else emp.row.ip_number) or ""
            values = [emp.row.row_number, emp.row.name, emp.row.agency, emp.row.state, identifier,
                      result.ecr_name, result.wagesheet_amount, result.ecr_amount, result.difference,
                      result.status.value, "Yes" if result.needs_review else "", result.reason, result.ecr_page]
            self._data_row(ws, index, values, status_col=10)
        self._finish_table(ws, len(headers), [6, 26, 22, 12, 16, 26, 14, 14, 14, 17, 10, 70, 8])

    def _combined_sheet(self, ws: Worksheet, employees: list[EmployeeResult]) -> None:
        headers = ["Row", "Employee name", "UAN", "IP Number", "PF status", "PF reason",
                   "ESIC status", "ESIC reason", "Action needed"]
        self._header(ws, 1, headers)
        for index, emp in enumerate(employees, start=2):
            action = "No" if (emp.pf.status == Status.MATCHED and emp.esic.status == Status.MATCHED
                              and not (emp.pf.needs_review or emp.esic.needs_review)) else "Yes"
            values = [emp.row.row_number, emp.row.name, emp.row.uan or "", emp.row.ip_number or "",
                      emp.pf.status.value, emp.pf.reason, emp.esic.status.value, emp.esic.reason, action]
            self._data_row(ws, index, values, status_col=5)
            ws.cell(index, 7).fill = STATUS_FILLS[emp.esic.status.value]
        self._finish_table(ws, len(headers), [6, 26, 16, 14, 17, 55, 17, 55, 10])

    def _ecr_only_sheet(self, ws: Worksheet, report: VerificationReport) -> None:
        headers = ["ECR", "Identifier", "Name in ECR", "Amount deposited", "Page", "Note"]
        self._header(ws, 1, headers)
        for index, member in enumerate(report.ecr_only, start=2):
            self._data_row(ws, index, [member.check, member.identifier, member.name, member.amount, member.page,
                                       "Filed by vendor but not on the wagesheet - confirm this person works here"])
        self._finish_table(ws, len(headers), [8, 16, 28, 16, 8, 70])

    def _parse_log_sheet(self, ws: Worksheet, report: VerificationReport) -> None:
        ws["A1"] = "Parse log"
        ws["A1"].font = TITLE_FONT
        row = 3
        self._header(ws, row, ["Document", "Pages", "Rows parsed", "Wrapped name lines", "Value errors",
                               "Skipped lines"])
        for label, log in (("PF ECR", report.pf_log), ("ESIC ECR", report.esic_log)):
            row += 1
            for col, value in enumerate([label, log.pages, log.rows_parsed, log.wrapped_name_lines,
                                         len(log.value_errors), len(log.skipped_lines)], start=1):
                ws.cell(row, col, value).border = BORDER

        row += 2
        ws.cell(row, 1, "Lines that were not member rows (headers, footers, page numbers):").font = Font(bold=True)
        for label, log in (("PF ECR", report.pf_log), ("ESIC ECR", report.esic_log)):
            for line in log.value_errors + log.skipped_lines:
                row += 1
                ws.cell(row, 1, label)
                ws.cell(row, 2, line)
        self._widths(ws, [12, 90, 12, 18, 12, 12])

    # ------------------------------------------------------------------ #
    # Styling helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _header(ws: Worksheet, row: int, labels: Iterable[str]) -> None:
        for col, label in enumerate(labels, start=1):
            cell = ws.cell(row, col, label)
            cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="center")

    @staticmethod
    def _data_row(ws: Worksheet, row: int, values: list, status_col: int | None = None) -> None:
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row, col, value)
            cell.border, cell.alignment = BORDER, WRAP
        if status_col:
            status_cell = ws.cell(row, status_col)
            if status_cell.value in STATUS_FILLS:
                status_cell.fill = STATUS_FILLS[status_cell.value]

    def _finish_table(self, ws: Worksheet, column_count: int, widths: list[int]) -> None:
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = f"A1:{get_column_letter(column_count)}{max(ws.max_row, 1)}"
        self._widths(ws, widths)

    @staticmethod
    def _widths(ws: Worksheet, widths: list[int]) -> None:
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width
