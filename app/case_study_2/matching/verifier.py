"""
The verification engine: wagesheet rows vs PF ECR and ESIC ECR.

PF and ESIC follow exactly the same logic, so both are described by a
`CheckSpec` and processed by one function. Adding a third statutory check
(e.g. LWF) would mean adding one more spec, not new logic.

Decision order for each employee and each check (first failing rule wins):
    1. Missing          no usable identifier in the wagesheet, or not in the ECR
    2. Name mismatch    identifier found, but the name is a different person
                        (an amount difference is mentioned in the reason too)
    3. Amount mismatch  identifier and name OK, amount differs by more than the tolerance
    4. Matched          everything agrees (flagged "needs review" for probable names)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

from app.case_study_2 import rules
from app.case_study_2.matching.amounts import amounts_match, format_rupees, round_nearest, round_up
from app.case_study_2.matching.names import NameMatcher
from app.case_study_2.models import (
    CheckResult,
    EcrOnlyMember,
    EmployeeResult,
    EsicEcrDocument,
    NameVerdict,
    PfEcrDocument,
    Status,
    WagesheetRow,
)


@dataclass(frozen=True)
class EcrEntry:
    """An ECR row reduced to what the verifier needs (same shape for PF and ESIC)."""

    identifier: str
    names: list[str]
    amount: Optional[float]
    wages: Optional[float]
    page: int


@dataclass(frozen=True)
class CheckSpec:
    label: str                     # "PF" / "ESIC"
    identifier_label: str          # "UAN" / "IP Number"
    wagesheet_amount_label: str    # "PF @ 12%"
    ecr_amount_label: str          # "EE share"
    rate: float
    rounding: Callable[[float], float]
    identifier_of: Callable[[WagesheetRow], Optional[str]]
    identifier_issue_of: Callable[[WagesheetRow], str]
    amount_of: Callable[[WagesheetRow], Optional[float]]


PF_CHECK = CheckSpec(
    label="PF",
    identifier_label="UAN",
    wagesheet_amount_label="PF @ 12%",
    ecr_amount_label="EE share",
    rate=rules.PF_EMPLOYEE_RATE,
    rounding=round_nearest,
    identifier_of=lambda row: row.uan,
    identifier_issue_of=lambda row: row.uan_issue,
    amount_of=lambda row: row.pf_amount,
)

ESIC_CHECK = CheckSpec(
    label="ESIC",
    identifier_label="IP Number",
    wagesheet_amount_label="ESIC @ 0.75%",
    ecr_amount_label="IP contribution",
    rate=rules.ESIC_EMPLOYEE_RATE,
    rounding=round_up,
    identifier_of=lambda row: row.ip_number,
    identifier_issue_of=lambda row: row.ip_issue,
    amount_of=lambda row: row.esic_amount,
)


def pf_entries(document: PfEcrDocument) -> list[EcrEntry]:
    return [
        EcrEntry(m.uan, [m.name_ecr, m.name_uan_repository], m.ee_share, m.epf_wages, m.page)
        for m in document.members
    ]


def esic_entries(document: EsicEcrDocument) -> list[EcrEntry]:
    return [EcrEntry(m.ip_number, [m.name], m.ip_contribution, m.wages, m.page) for m in document.members]


@dataclass
class VerificationOutcome:
    employees: list[EmployeeResult]
    ecr_only: list[EcrOnlyMember]
    warnings: list[str]


class ContributionVerifier:
    def __init__(self, name_matcher: Optional[NameMatcher] = None):
        self.names = name_matcher or NameMatcher()

    def verify(self, rows: list[WagesheetRow], pf_doc: PfEcrDocument,
               esic_doc: EsicEcrDocument) -> VerificationOutcome:
        warnings: list[str] = []
        pf_index = self._build_index(pf_entries(pf_doc), PF_CHECK, warnings)
        esic_index = self._build_index(esic_entries(esic_doc), ESIC_CHECK, warnings)

        employees = [
            EmployeeResult(
                row=row,
                pf=self.check(row, pf_index, PF_CHECK),
                esic=self.check(row, esic_index, ESIC_CHECK),
            )
            for row in rows
        ]
        self._note_duplicate_identifiers(employees, warnings)

        ecr_only = self._ecr_only(rows, pf_index, PF_CHECK) + self._ecr_only(rows, esic_index, ESIC_CHECK)
        return VerificationOutcome(employees, ecr_only, warnings)

    # ------------------------------------------------------------------ #
    # One employee, one check
    # ------------------------------------------------------------------ #

    def check(self, row: WagesheetRow, index: dict[str, EcrEntry], spec: CheckSpec) -> CheckResult:
        identifier = spec.identifier_of(row)
        wagesheet_amount = spec.amount_of(row)

        if identifier is None:
            return CheckResult(
                status=Status.MISSING,
                reason=f"{spec.identifier_issue_of(row)}, so it cannot be checked against the {spec.label} ECR.",
                wagesheet_amount=wagesheet_amount,
            )

        entry = index.get(identifier)
        if entry is None:
            return CheckResult(
                status=Status.MISSING,
                reason=f"{spec.identifier_label} {identifier} does not appear in the {spec.label} ECR.",
                identifier=identifier,
                wagesheet_amount=wagesheet_amount,
            )

        name = self.names.compare_best(row.name, entry.names)
        expected = spec.rounding(entry.wages * spec.rate) if entry.wages is not None else None
        difference = (
            round(entry.amount - wagesheet_amount, 2)
            if entry.amount is not None and wagesheet_amount is not None else None
        )
        amount_ok = amounts_match(wagesheet_amount, entry.amount)
        amount_text = self._describe_amounts(spec, wagesheet_amount, entry, expected)

        base = dict(
            identifier=identifier,
            ecr_name=name.compared_with or entry.names[0],
            wagesheet_amount=wagesheet_amount,
            ecr_amount=entry.amount,
            difference=difference,
            expected_from_ecr_wages=expected,
            name_verdict=name.verdict,
            ecr_page=entry.page,
        )
        ecr_name_note = self._ecr_internal_name_note(entry)

        if name.verdict == NameVerdict.CONFLICT:
            reason = (f"{spec.identifier_label} found but the name differs "
                      f"(wagesheet: {row.name}; ECR: {base['ecr_name']}) - {name.explanation}.")
            if not amount_ok:
                reason += f" Amount also differs: {amount_text}"
            return CheckResult(status=Status.NAME_MISMATCH, reason=_join(reason, ecr_name_note), **base)

        needs_review = name.verdict == NameVerdict.PROBABLE or bool(ecr_name_note)
        name_note = "" if name.explanation in ("exact match", "match") else f"Name: {name.explanation}."

        if not amount_ok:
            return CheckResult(status=Status.AMOUNT_MISMATCH, needs_review=needs_review,
                               reason=_join(amount_text, name_note, ecr_name_note), **base)

        return CheckResult(
            status=Status.MATCHED,
            needs_review=needs_review,
            reason=_join(f"{spec.identifier_label}, name and amount match.", name_note, ecr_name_note),
            **base,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _describe_amounts(spec: CheckSpec, wagesheet_amount: Optional[float],
                          entry: EcrEntry, expected: Optional[float]) -> str:
        if wagesheet_amount is None:
            return f"{spec.wagesheet_amount_label} is blank in the wagesheet."
        if entry.amount is None:
            return f"The {spec.ecr_amount_label} could not be read from the ECR (page {entry.page})."

        difference = entry.amount - wagesheet_amount
        direction = "short by" if difference < 0 else "more by"
        text = (f"Wagesheet {spec.wagesheet_amount_label} {format_rupees(wagesheet_amount)} vs "
                f"ECR {spec.ecr_amount_label} {format_rupees(entry.amount)}: deposit {direction} "
                f"{format_rupees(abs(difference))}.")

        if expected is not None and abs(difference) > rules.AMOUNT_TOLERANCE_RUPEES:
            tolerance = rules.AMOUNT_TOLERANCE_RUPEES
            basis = f"{spec.rate * 100:g}% of ECR wages {format_rupees(entry.wages)} = {format_rupees(expected)}"
            if abs(expected - wagesheet_amount) <= tolerance:
                text += f" Cross-check: {basis}, so the ECR deposit is wrong."
            elif abs(expected - entry.amount) <= tolerance:
                text += f" Cross-check: {basis}, so the wagesheet figure is wrong."
        return text

    def _ecr_internal_name_note(self, entry: EcrEntry) -> str:
        """The PF ECR has two names; flag if they disagree with each other."""
        names = [n for n in entry.names if n]
        if len(names) < 2:
            return ""
        if self.names.compare(names[0], names[1]).verdict == NameVerdict.CONFLICT:
            return f"ECR name '{names[0]}' and UAN-repository name '{names[1]}' differ."
        return ""

    @staticmethod
    def _build_index(entries: list[EcrEntry], spec: CheckSpec, warnings: list[str]) -> dict[str, EcrEntry]:
        index: dict[str, EcrEntry] = {}
        for entry in entries:
            if entry.identifier in index:
                warnings.append(
                    f"{spec.label} ECR lists {spec.identifier_label} {entry.identifier} more than once "
                    f"(pages {index[entry.identifier].page} and {entry.page}); the first entry was used."
                )
                continue
            index[entry.identifier] = entry
        return index

    @staticmethod
    def _note_duplicate_identifiers(employees: list[EmployeeResult], warnings: list[str]) -> None:
        for spec, attr in ((PF_CHECK, "pf"), (ESIC_CHECK, "esic")):
            rows_by_id: dict[str, list[int]] = defaultdict(list)
            for emp in employees:
                identifier = spec.identifier_of(emp.row)
                if identifier:
                    rows_by_id[identifier].append(emp.row.row_number)
            for identifier, row_numbers in rows_by_id.items():
                if len(row_numbers) < 2:
                    continue
                warnings.append(f"Wagesheet repeats {spec.identifier_label} {identifier} on rows "
                                f"{', '.join(map(str, row_numbers))}.")
                for emp in employees:
                    if spec.identifier_of(emp.row) == identifier:
                        result: CheckResult = getattr(emp, attr)
                        result.reason = _join(result.reason, f"Same {spec.identifier_label} also on wagesheet "
                                                             f"row(s) {', '.join(map(str, row_numbers))}.")
                        result.needs_review = True

    @staticmethod
    def _ecr_only(rows: list[WagesheetRow], index: dict[str, EcrEntry], spec: CheckSpec) -> list[EcrOnlyMember]:
        wagesheet_ids = {spec.identifier_of(r) for r in rows}
        return [
            EcrOnlyMember(spec.label, entry.identifier, entry.names[0], entry.amount, entry.page)
            for identifier, entry in index.items()
            if identifier not in wagesheet_ids
        ]


def _join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())
