"""
Generate realistic synthetic test sets (wagesheet + PF ECR PDF + ESIC ECR PDF + answer key).

Each employee gets an independent, randomly chosen *scenario* for PF and for
ESIC (clean, spelling variant, initial, wrong first name, short deposit,
missing ...). Every scenario has a known expected status, written to
`expected_results.csv`, so `scripts/evaluate.py` can measure accuracy.

The PDFs imitate the EPFO / ESIC layouts of the provided samples (same
column order and header words) and add the things real files have:
many pages, long names that wrap onto a second line, footers, and - in one
set - continuation pages without a repeated table header.

Usage:
    python scripts/case_study_2/generate_test_data.py   # writes data/case_study_2/synthetic/
"""

from __future__ import annotations

import csv
import math
import random
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]          # project root (scripts/case_study_2/ -> ../..)
OUTPUT_DIR = ROOT / "data" / "case_study_2" / "synthetic"

# ---------------------------------------------------------------------------
# Name pools
# ---------------------------------------------------------------------------
MALE = ["RAKESH", "DINESH", "SUNIL", "MAHESH", "AMIT", "VIJAY", "DEEPAK", "RAJEEV", "SANJEEV", "MANOJ", "ANIL",
        "SURESH", "RAMESH", "ARVIND", "PANKAJ", "VIKAS", "SANJAY", "ASHOK", "PRADEEP", "YOGESH", "RAHUL", "ROHIT",
        "MOHAMMAD", "IMRAN", "SALMAN", "GURPREET", "HARISH", "NAVEEN", "PRAKASH", "SATISH", "VINOD", "AJAY"]
FEMALE = ["REKHA", "SUNITA", "POOJA", "PREETI", "NEETU", "SHWETA", "SEEMA", "GEETA", "ANITA", "PRIYA", "ASHA",
          "NEHA", "KAVITA", "MAMTA", "SAROJ", "LAXMI", "REENA", "SONIA", "JYOTI", "KOMAL", "NISHA", "VEENA"]
SURNAMES = ["SHARMA", "VERMA", "GUPTA", "YADAV", "SINGH", "PRASAD", "KUMAR", "MISHRA", "PASWAN", "THAKUR", "CHAUHAN",
            "RAWAT", "MEENA", "JAIN", "KHAN", "ANSARI", "PANDEY", "TIWARI", "DUBEY", "SAINI", "BISHT", "NEGI",
            "CHAUDHARY", "MAURYA", "KUSHWAHA", "QURESHI", "BHARDWAJ", "SRIVASTAVA"]
MIDDLE = ["KUMAR", "LAL", "CHAND", "PRASAD", "DEVI", "KUMARI", "RANI", "SINGH"]

# Same name, different spelling -> must be MATCHED
SPELLING_VARIANTS = {
    "SUNITA": "SUNEETA", "POOJA": "PUJA", "DEEPAK": "DIPAK", "PREETI": "PRITI", "RAJEEV": "RAJIV",
    "SANJEEV": "SANJIV", "NEETU": "NITU", "SHWETA": "SWETA", "SEEMA": "SIMA", "GEETA": "GITA", "VIJAY": "VIJAI",
    "MOHAMMAD": "MOHD", "VEENA": "VINA", "ANITA": "ANEETA", "GUPTA": "GUPTHA", "PRASAD": "PRASHAD",
    "CHAUDHARY": "CHOUDHARY", "SRIVASTAVA": "SHRIVASTAVA", "LAXMI": "LAKSHMI", "PRADEEP": "PRADIP",
}
# Different people with similar names -> must be NAME MISMATCH
CONFUSABLE = {
    "RAKESH": "RAMESH", "REKHA": "RENU", "DINESH": "DEVENDRA", "SUNIL": "SUSHIL", "MAHESH": "MUKESH",
    "ASHA": "USHA", "PRIYA": "PRIYANKA", "AMIT": "AMAN", "SEEMA": "SUMAN", "NEHA": "NEETA", "ANIL": "AKHIL",
    "VIKAS": "VIKRAM", "SURESH": "SUBHASH", "KAVITA": "KAMLA", "MANOJ": "MANISH", "ROHIT": "MOHIT",
}

# ---------------------------------------------------------------------------
# Scenarios: (name, expected status, weight)
# ---------------------------------------------------------------------------
MATCHED, NAME, AMOUNT, MISSING = "Matched", "Name mismatch", "Amount mismatch", "Missing"

SCENARIOS = {
    "clean": MATCHED,
    "spelling_variant": MATCHED,
    "word_order": MATCHED,
    "title_in_ecr": MATCHED,
    "rounding_within_1": MATCHED,
    "initial_in_ecr": MATCHED,          # needs review
    "extra_name_part": MATCHED,         # needs review
    "first_name_conflict": NAME,
    "surname_conflict": NAME,
    "name_and_amount": NAME,
    "short_deposit": AMOUNT,
    "wagesheet_wrong": AMOUNT,
    "missing_in_ecr": MISSING,
    "blank_id": MISSING,
}


@dataclass
class Scenario:
    """Configuration of one generated test set."""

    folder: str
    description: str
    size: int
    weights: dict[str, float]
    seed: int
    alias_headers: bool = False
    messy_ids: bool = False            # ints / floats / spaces / scientific notation in Excel
    repeat_table_header: bool = True
    ecr_only_extra: int = 0
    esic_month_override: Optional[str] = None
    agency: str = "SAMPLE STAFFING PRIVATE LIMITED"


DEFAULT_WEIGHTS = {
    "clean": 55, "spelling_variant": 8, "word_order": 4, "title_in_ecr": 3, "rounding_within_1": 3,
    "initial_in_ecr": 2, "extra_name_part": 2, "first_name_conflict": 4, "surname_conflict": 2,
    "name_and_amount": 1, "short_deposit": 6, "wagesheet_wrong": 2, "missing_in_ecr": 5, "blank_id": 1,
}

SETS = [
    Scenario(
        folder="set_01_name_variants",
        description="40 employees, heavy on spelling / order / initial variations - tests 'no crying wolf'.",
        size=40, seed=11,
        weights={**DEFAULT_WEIGHTS, "clean": 20, "spelling_variant": 20, "word_order": 10, "title_in_ecr": 8,
                 "initial_in_ecr": 6, "extra_name_part": 6, "first_name_conflict": 8, "blank_id": 0},
    ),
    Scenario(
        folder="set_02_messy_vendor_file",
        description="220 employees, vendor-style headers with a title row, Excel-damaged IDs, ECR-only members, "
                    "wage-month mismatch between the two ECRs.",
        size=220, seed=22, weights={**DEFAULT_WEIGHTS, "blank_id": 2}, alias_headers=True, messy_ids=True,
        ecr_only_extra=4, esic_month_override="SEP-2025", agency="XYZ MANPOWER SERVICES LLP",
    ),
    Scenario(
        folder="set_03_large_scale",
        description="1,500 employees (~70 PF pages); continuation pages do not repeat the table header.",
        size=1500, seed=33, weights=DEFAULT_WEIGHTS, repeat_table_header=False, ecr_only_extra=10,
        agency="BIG FLEET FACILITY SERVICES PVT LTD",
    ),
]


# ---------------------------------------------------------------------------
# Data model for generation
# ---------------------------------------------------------------------------

@dataclass
class Person:
    name: str
    uan: str
    ip: str
    gross_wages: int
    days: int

    @property
    def epf_wages(self) -> int:
        return min(self.gross_wages, 15000)


@dataclass
class WagesheetLine:
    person: Person
    name: str
    uan_cell: object
    ip_cell: object
    pf_amount: float
    esic_amount: float
    expected_pf: str
    expected_esic: str
    pf_scenario: str
    esic_scenario: str


@dataclass
class PfLine:
    uan: str
    name_ecr: str
    name_repo: str
    gross: int
    epf: int
    ee: int
    eps: int
    er: int
    ncp: int


@dataclass
class EsicLine:
    ip: str
    name: str
    days: int
    wages: int
    contribution: int
    reason: str


@dataclass
class Dataset:
    wagesheet: list[WagesheetLine] = field(default_factory=list)
    pf: list[PfLine] = field(default_factory=list)
    esic: list[EsicLine] = field(default_factory=list)


def pf_share(wages: int) -> int:
    return int(Decimal(wages * 0.12).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def esic_share(wages: int) -> int:
    return math.ceil(round(wages * 0.0075, 4))


# ---------------------------------------------------------------------------
# Builder: people -> scenarios -> wagesheet / ECR lines
# ---------------------------------------------------------------------------

class DatasetBuilder:
    def __init__(self, scenario: Scenario):
        self.s = scenario
        self.rng = random.Random(scenario.seed)

    def build(self) -> Dataset:
        data = Dataset()
        people = [self._person(i) for i in range(self.s.size + self.s.ecr_only_extra)]
        employees, extras = people[:self.s.size], people[self.s.size:]

        for person in employees:
            pf_scn, esic_scn = self._pick_scenario(), self._pick_scenario()
            line = self._wagesheet_line(person, pf_scn, esic_scn)
            data.wagesheet.append(line)
            if pf_scn not in ("missing_in_ecr",):
                data.pf.append(self._pf_line(person, pf_scn, line))
            if esic_scn not in ("missing_in_ecr",):
                data.esic.append(self._esic_line(person, esic_scn, line))

        for person in extras:  # filed by the vendor, not on the wagesheet
            data.pf.append(self._pf_line(person, "clean", None))
            data.esic.append(self._esic_line(person, "clean", None))

        self.rng.shuffle(data.pf)    # ECR order never matches the wagesheet order
        self.rng.shuffle(data.esic)
        return data

    # -- people -------------------------------------------------------------

    def _person(self, index: int) -> Person:
        first = self.rng.choice(MALE + FEMALE)
        parts = [first]
        if self.rng.random() < 0.18:
            parts.append(self.rng.choice(MIDDLE))
        parts.append(self.rng.choice(SURNAMES))
        if self.rng.random() < 0.04:  # a few long names to force wrapping in the PDF
            parts.insert(1, self.rng.choice(["IRFAN", "PRAKASH", "CHANDRA", "MOHAN"]))
        uan = f"10{self.s.seed:02d}{index:08d}"
        ip = f"2{self.s.seed % 10}{index:08d}"
        return Person(" ".join(dict.fromkeys(parts)), uan, ip,
                      gross_wages=self.rng.randrange(9000, 20500, 10), days=self.rng.randint(20, 31))

    def _pick_scenario(self) -> str:
        names, weights = zip(*self.s.weights.items())
        return self.rng.choices(names, weights=weights)[0]

    # -- wagesheet ----------------------------------------------------------

    def _wagesheet_line(self, p: Person, pf_scn: str, esic_scn: str) -> WagesheetLine:
        pf_amount, esic_amount = float(pf_share(p.epf_wages)), float(esic_share(p.gross_wages))
        if pf_scn == "wagesheet_wrong":
            pf_amount += self.rng.choice([-1, 1]) * self.rng.randint(40, 300)
        if esic_scn == "wagesheet_wrong":
            esic_amount += self.rng.choice([-1, 1]) * self.rng.randint(5, 40)
        if pf_scn == "rounding_within_1":
            pf_amount += self.rng.choice([-1, 1])
        if esic_scn == "rounding_within_1":
            esic_amount += self.rng.choice([-1, 1])

        uan_cell, ip_cell = self._id_cell(p.uan), self._id_cell(p.ip)
        expected_pf, expected_esic = SCENARIOS[pf_scn], SCENARIOS[esic_scn]
        if pf_scn == "blank_id":
            uan_cell = None
        elif self.s.messy_ids and self.rng.random() < 0.01:
            uan_cell, expected_pf, pf_scn = f"{int(p.uan):.5E}".replace("E+", "E+"), MISSING, "excel_scientific_uan"
        if esic_scn == "blank_id":
            ip_cell = None

        display_name = p.name
        if self.rng.random() < 0.05:
            display_name = p.name.title()  # mixed case in the wagesheet
        return WagesheetLine(p, display_name, uan_cell, ip_cell, pf_amount, esic_amount,
                             expected_pf, expected_esic, pf_scn, esic_scn)

    def _id_cell(self, identifier: str) -> object:
        if not self.s.messy_ids:
            return identifier
        roll = self.rng.random()
        if roll < 0.40:
            return int(identifier)           # Excel number
        if roll < 0.50:
            return float(identifier)         # 101200000012.0
        if roll < 0.55:
            return f"{identifier[:4]} {identifier[4:8]} {identifier[8:]}"  # typed with spaces
        return identifier

    # -- ECR names ----------------------------------------------------------

    def _ecr_name(self, name: str, scenario: str) -> str:
        words = name.split()
        if scenario == "spelling_variant":
            for i, w in enumerate(words):
                if w in SPELLING_VARIANTS:
                    words[i] = SPELLING_VARIANTS[w]
                    return " ".join(words)
            # no known variant for this name: double a vowel, which sounds the same
            words[0] = words[0].replace("I", "EE", 1) if "I" in words[0] else words[0]
        elif scenario == "word_order" and len(words) >= 2:
            words = words[-1:] + words[:-1]
        elif scenario == "title_in_ecr":
            words = ["SMT." if words[0] in FEMALE else "MR."] + words
        elif scenario == "initial_in_ecr" and len(words) >= 2:
            words[0] = words[0][0]
        elif scenario == "extra_name_part":
            extra = next(m for m in ["KUMAR", "SINGH", "DEVI", "LAL"] if m not in words)
            words.insert(1, extra)
        elif scenario in ("first_name_conflict", "name_and_amount"):
            words[0] = CONFUSABLE.get(words[0]) or self._different_first_name(words[0])
        elif scenario == "surname_conflict":
            words[-1] = self.rng.choice([s for s in SURNAMES if s[0] != words[-1][0] and s not in words])
        return " ".join(words)

    def _different_first_name(self, first: str) -> str:
        # different first letter guarantees a genuinely different name
        return self.rng.choice([n for n in MALE + FEMALE if n[0] != first[0]])

    # -- ECR lines ----------------------------------------------------------

    def _pf_line(self, p: Person, scenario: str, ws: Optional[WagesheetLine]) -> PfLine:
        name = self._ecr_name(p.name, scenario)
        ee = pf_share(p.epf_wages)
        if scenario in ("short_deposit", "name_and_amount"):
            ee -= self.rng.randint(50, 400)
        eps = min(round(p.epf_wages * 0.0833), 1250)
        repo_name = name if self.rng.random() > 0.03 or scenario != "clean" else p.name
        return PfLine(p.uan, name, repo_name, p.gross_wages, p.epf_wages, ee, eps, max(ee - eps, 0),
                      ncp=31 - p.days if p.days < 31 else 0)

    def _esic_line(self, p: Person, scenario: str, ws: Optional[WagesheetLine]) -> EsicLine:
        name = self._ecr_name(p.name, scenario)
        contribution = esic_share(p.gross_wages)
        if scenario in ("short_deposit", "name_and_amount"):
            contribution -= self.rng.randint(5, min(60, contribution - 1))
        reason = "-" if self.rng.random() > 0.03 else self.rng.choice(["On Leave", "Left Service"])
        return EsicLine(p.ip, name, p.days, p.gross_wages, contribution, reason)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

TEMPLATE_HEADERS = ["Name", "UAN", "IP Number", "Agency", "State", "ESIC @ 0.75%", "PF @ 12%"]
ALIAS_HEADERS = ["Employee Name", "UAN No.", "ESIC IP No", "Contractor", "Location", "ESI (0.75%)", "EPF (12%)"]
STATES = ["Haryana", "Delhi", "Uttar Pradesh", "Bihar", "Maharashtra", "Karnataka"]


def write_wagesheet(path: Path, data: Dataset, s: Scenario) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Wagesheet"
    if s.alias_headers:
        sheet.append([f"Wage sheet - {s.agency.title()} - Aug 2025"])
        sheet["A1"].font = Font(bold=True, size=13)
        sheet.append([])
    sheet.append(ALIAS_HEADERS if s.alias_headers else TEMPLATE_HEADERS)
    rng = random.Random(s.seed)
    for line in data.wagesheet:
        sheet.append([line.name, line.uan_cell, line.ip_cell, s.agency.title(), rng.choice(STATES),
                      line.esic_amount, line.pf_amount])
    workbook.save(path)


def write_expected(path: Path, data: Dataset, header_rows: int) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_number", "name", "uan", "ip_number", "expected_pf_status", "expected_esic_status",
                         "pf_scenario", "esic_scenario"])
        for index, line in enumerate(data.wagesheet, start=header_rows + 1):
            writer.writerow([index, line.name, line.person.uan, line.person.ip, line.expected_pf, line.expected_esic,
                             line.pf_scenario, line.esic_scenario])


class EcrPdfWriter:
    """Shared drawing helpers. Coordinates are 'top' values like pdfplumber reports them."""

    FONT, BOLD, SIZE = "Helvetica", "Helvetica-Bold", 8.5
    PAGE_W, PAGE_H = A4
    BOTTOM_LIMIT = 790

    def __init__(self, path: Path):
        self.c = canvas.Canvas(str(path), pagesize=A4)

    def text(self, x: float, top: float, value: str, bold: bool = False, size: float | None = None,
             right: bool = False) -> None:
        size = size or self.SIZE
        self.c.setFont(self.BOLD if bold else self.FONT, size)
        y = self.PAGE_H - top - size
        (self.c.drawRightString if right else self.c.drawString)(x, y, str(value))

    def wrap(self, value: str, width: float) -> list[str]:
        lines, current = [], ""
        for word in value.split():
            candidate = f"{current} {word}".strip()
            if stringWidth(candidate, self.FONT, self.SIZE) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        return lines + ([current] if current else [])

    def save(self) -> None:
        self.c.save()


class PfEcrWriter(EcrPdfWriter):
    # (key, header x, value right edge or None for left-aligned text)
    UPPER = [("Name as per", 209), ("Gross", 294), ("EPF", 333), ("EPS", 373), ("EDLI", 413), ("NCP", 555)]
    HEADER = [("Sl. No.", 24), ("UAN", 56), ("Name as per ECR", 124), ("UAN Repository", 209), ("Wages", 294),
              ("Wages", 333), ("Wages", 373), ("Wages", 413), ("EE", 452), ("EPS", 486), ("ER", 520), ("Days", 555)]
    NAME_WIDTH = 80

    def write(self, data: Dataset, s: Scenario) -> None:
        rows = data.pf
        total_ee, total_eps = sum(r.ee for r in rows), sum(r.eps for r in rows)
        pages = self._paginate(rows, s)
        for page_no, page_rows in enumerate(pages, start=1):
            if page_no == 1:
                self._first_page_header(s, len(rows), total_ee, total_eps)
                top = self._table_header(314)
            elif s.repeat_table_header:
                top = self._table_header(30)
            else:
                top = 40
            for sl, row in page_rows:
                top = self._row(top, sl, row)
            self.text(46, 812, f"DLCPM{s.seed:010d} / AUG-2025 / 15-SEP-2025 20:39", size=7.5)
            self.text(470, 812, f"Page {page_no} of {len(pages)}", size=7.5)
            self.c.showPage()
        self.save()

    def _paginate(self, rows: list[PfLine], s: Scenario) -> list[list[tuple[int, PfLine]]]:
        first_body, other_body = 363, (72 if s.repeat_table_header else 40)
        pages, current, top = [], [], first_body
        for sl, row in enumerate(rows, start=1):
            height = self._row_height(row)
            if top + height > self.BOTTOM_LIMIT and current:
                pages.append(current)
                current, top = [], other_body
            current.append((sl, row))
            top += height
        pages.append(current)
        return pages

    def _row_height(self, row: PfLine) -> float:
        lines = max(len(self.wrap(row.name_ecr, self.NAME_WIDTH)), len(self.wrap(row.name_repo, self.NAME_WIDTH)))
        return 22 + 10 * (lines - 1)

    def _first_page_header(self, s: Scenario, members: int, total_ee: int, total_eps: int) -> None:
        self.text(167, 51, "EMPLOYEE'S PROVIDENT FUND ORGANISATION", bold=True, size=10)
        self.text(196, 64, "ELECTRONIC CHALLAN CUM RETURN (ECR)", bold=True, size=10)
        left = [("Name of Establishment", s.agency), ("Establishment Id", f"DLCPM{s.seed:010d}"),
                ("Wage Month", "AUG-2025"), ("Contribution Rate (%)", "12"), ("Salary Disbursement Date", "08-SEP-2025"),
                ("Exemption Status", "Unexempted"), ("Remarks", "SYNTHETIC TEST DATA"),
                ("Total Members", str(members))]
        right = {1: ("LIN", "9999999999"), 2: ("Return Month", "SEP-2025"), 3: ("ECR Type", "ECR"),
                 4: ("Uploaded Date Time", "15-SEP-2025 20:39"), 5: ("TRRN Number", ""), 6: ("ECR Id", "999000001")}
        for i, (label, value) in enumerate(left):
            top = 89 + 20 * i
            self.text(46, top, label)
            self.text(182, top, value)
            if i in right:
                self.text(357, top, right[i][0])
                self.text(471, top, right[i][1])
        self.text(46, 254, "Contribution and Remittance Details (In Rupees) :")
        self.text(49, 267, "Total EPF Contribution")
        self.text(196, 267, f"{total_ee:,}")
        self.text(304, 267, "Total EPS Contribution")
        self.text(451, 267, f"{total_eps:,}")
        self.text(49, 287, "Total EPF-EPS Contribution")
        self.text(196, 287, f"{total_ee - total_eps:,}")
        self.text(304, 287, "Total Refund Advance")
        self.text(451, 287, "0")

    def _table_header(self, top: float) -> float:
        if top > 300:
            self.text(46, top, "Member Details :")
            top += 17
        for label, x in self.UPPER:
            self.text(x, top, label, bold=True)
        for label, x in self.HEADER:
            self.text(x, top + 12, label, bold=True)
        return top + 32

    def _row(self, top: float, sl: int, row: PfLine) -> float:
        self.text(24, top, str(sl))
        self.text(56, top, row.uan)
        for x, name in ((124, row.name_ecr), (209, row.name_repo)):
            for i, part in enumerate(self.wrap(name, self.NAME_WIDTH)):
                self.text(x, top + 10 * i, part)
        values = [(321, row.gross), (361, row.epf), (401, row.epf), (440, row.epf),
                  (474, row.ee), (508, row.eps), (543, row.er), (571, row.ncp)]
        for right_edge, value in values:
            self.text(right_edge, top, f"{value:,}", right=True)
        return top + self._row_height(row)


class EsicEcrWriter(EcrPdfWriter):
    NAME_WIDTH = 140

    def write(self, data: Dataset, s: Scenario) -> None:
        rows = data.esic
        totals = {
            "ip": sum(r.contribution for r in rows),
            "wages": sum(r.wages for r in rows),
        }
        totals["employer"] = sum(math.ceil(r.wages * 0.0325) for r in rows)
        month = s.esic_month_override or "AUG-2025"
        month_text = month[:1] + month[1:3].lower() + month[4:]   # "Aug2025"

        pages, current, top = [], [], 158
        for sno, row in enumerate(rows, start=1):
            height = 24 + 10 * (len(self.wrap(row.name, self.NAME_WIDTH)) - 1)
            if top + height > self.BOTTOM_LIMIT and current:
                pages.append(current)
                current, top = [], 60
            current.append((sno, row, height))
            top += height
        pages.append(current)

        for page_no, page_rows in enumerate(pages, start=1):
            if page_no == 1:
                self.text(190, 51, "Employees' State Insurance Corporation", bold=True, size=10)
                self.text(170, 67, f"Contribution History Of 99000000000{s.seed:06d} for {month_text}", size=9)
                labels = [(49, "Total IP Contribution", totals["ip"]),
                          (142, "Total Employer Contribution", totals["employer"]),
                          (255, "Total Contribution", totals["ip"] + totals["employer"]),
                          (343, "Total Government Contribution", 0),
                          (465, "Total Monthly Wages", totals["wages"])]
                for x, label, value in labels:
                    self.text(x, 91, label, size=7.5)
                    self.text(x, 110, f"{value:.2f}")
                top = self._table_header(137)
            else:
                top = self._table_header(40)
            for sno, row, height in page_rows:
                self._row(top, sno, row)
                top += height
            self.text(49, 812, f"Page {page_no} of {len(pages)}", size=7.5)
            self.text(149, 812, "Printed On: 9/12/2025 18:08:28", size=7.5)
            self.c.showPage()
        self.save()

    def _table_header(self, top: float) -> float:
        for x, label in [(29, "SNo."), (63, "Is Disable"), (114, "IP Number"), (187, "IP Name"),
                         (335, "No. Of Days"), (392, "Total Wages"), (460, "IP Contribution"), (533, "Reason")]:
            self.text(x, top, label, bold=True)
        return top + 21

    def _row(self, top: float, sno: int, row: EsicLine) -> None:
        self.text(29, top, str(sno))
        self.text(63, top, "-")
        self.text(114, top, row.ip)
        for i, part in enumerate(self.wrap(row.name, self.NAME_WIDTH)):
            self.text(187, top + 10 * i, part)
        self.text(344, top, str(row.days), right=True)
        self.text(425, top, f"{row.wages:.2f}", right=True)
        self.text(484, top, f"{row.contribution:.2f}", right=True)
        self.text(533, top, row.reason)


# ---------------------------------------------------------------------------
# Bad-input samples (for the error-handling demo)
# ---------------------------------------------------------------------------

def write_bad_inputs(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "corrupt_pf_ecr.pdf").write_bytes(b"%PDF-1.4\n" + bytes(random.Random(1).randbytes(600)))
    (folder / "renamed_excel_as_pdf.pdf").write_bytes((ROOT / "data/case_study_2/sample/Sample_Wagesheet_Aug25.xlsx").read_bytes())

    workbook = openpyxl.Workbook()
    workbook.active.append(["Name", "Department", "Salary"])
    workbook.active.append(["ANIL KUMAR", "Ops", 13520])
    workbook.save(folder / "wagesheet_wrong_columns.xlsx")

    workbook = openpyxl.Workbook()
    workbook.active.append(TEMPLATE_HEADERS)
    workbook.save(folder / "wagesheet_header_only.xlsx")

    # Image-only "scan": text drawn as an image has no text layer.
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (1240, 400), "white")
    ImageDraw.Draw(image).text((40, 40), "EMPLOYEE'S PROVIDENT FUND ORGANISATION - scanned copy", fill="black")
    image_path = folder / "_scan.png"
    image.save(image_path)
    pdf = canvas.Canvas(str(folder / "scanned_pf_ecr.pdf"), pagesize=A4)
    pdf.drawImage(str(image_path), 30, 500, width=535, height=170)
    pdf.save()
    image_path.unlink()

    pdf = canvas.Canvas(str(folder / "not_an_ecr_invoice.pdf"), pagesize=A4)
    pdf.drawString(50, 780, "TAX INVOICE - Housekeeping services for the month of August 2025")
    pdf.drawString(50, 760, "Invoice No 4471    Amount payable Rs 1,24,000")
    pdf.save()


# ---------------------------------------------------------------------------

def generate(scenario: Scenario) -> dict:
    folder = OUTPUT_DIR / scenario.folder
    folder.mkdir(parents=True, exist_ok=True)
    data = DatasetBuilder(scenario).build()

    write_wagesheet(folder / "wagesheet.xlsx", data, scenario)
    write_expected(folder / "expected_results.csv", data, header_rows=3 if scenario.alias_headers else 1)
    PfEcrWriter(folder / "pf_ecr.pdf").write(data, scenario)
    EsicEcrWriter(folder / "esic_ecr.pdf").write(data, scenario)
    (folder / "ABOUT.txt").write_text(scenario.description + "\n")

    return {"set": scenario.folder, "employees": len(data.wagesheet), "pf_rows": len(data.pf),
            "esic_rows": len(data.esic)}


def main() -> None:
    for scenario in SETS:
        print(generate(scenario))
    write_bad_inputs(OUTPUT_DIR / "bad_inputs")
    print("bad inputs written to", OUTPUT_DIR / "bad_inputs")


if __name__ == "__main__":
    sys.exit(main())
