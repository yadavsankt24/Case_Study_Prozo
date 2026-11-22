"""
Domain models shared by parsers, matching engine, reporting and storage.

Plain dataclasses (no framework types) so the core logic can be tested and
reused from the web app, the CLI and the test-suite alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Status(str, Enum):
    """Verification verdict for one employee against one ECR."""

    MATCHED = "Matched"
    NAME_MISMATCH = "Name mismatch"
    AMOUNT_MISMATCH = "Amount mismatch"
    MISSING = "Missing"


class NameVerdict(str, Enum):
    """Outcome of comparing two names."""

    MATCH = "match"        # same person (exact or a known spelling variation)
    PROBABLE = "probable"  # very likely the same person, but a human should glance at it
    CONFLICT = "conflict"  # a name part clearly differs -> different person


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class WagesheetRow:
    """One employee row from the vendor's wagesheet."""

    row_number: int               # row number as seen in Excel (for traceability)
    name: str
    uan: Optional[str]            # normalised 12-digit UAN, or None if absent/invalid
    ip_number: Optional[str]      # normalised 10-digit IP number, or None
    pf_amount: Optional[float]
    esic_amount: Optional[float]
    agency: str = ""
    state: str = ""
    uan_issue: str = ""           # why the UAN could not be used (if any)
    ip_issue: str = ""            # why the IP number could not be used (if any)


@dataclass
class PfEcrMember:
    """One member row from the EPFO Electronic Challan cum Return."""

    uan: str
    name_ecr: str
    name_uan_repository: str
    gross_wages: Optional[float]
    epf_wages: Optional[float]
    eps_wages: Optional[float]
    edli_wages: Optional[float]
    ee_share: Optional[float]     # employee PF contribution -> compared with wagesheet "PF @ 12%"
    eps_share: Optional[float]
    er_share: Optional[float]
    ncp_days: Optional[float]
    page: int


@dataclass
class EsicEcrMember:
    """One insured-person row from the ESIC contribution history."""

    ip_number: str
    name: str
    days: Optional[float]
    wages: Optional[float]
    ip_contribution: Optional[float]  # employee ESIC -> compared with wagesheet "ESIC @ 0.75%"
    reason: str
    page: int


@dataclass
class ParseLog:
    """What the PDF parser saw; shown to users so parsing problems are never silent."""

    pages: int = 0
    rows_parsed: int = 0
    wrapped_name_lines: int = 0
    skipped_lines: list[str] = field(default_factory=list)  # "p3: <text>"
    value_errors: list[str] = field(default_factory=list)


@dataclass
class PfEcrDocument:
    members: list[PfEcrMember]
    header: dict                  # establishment, wage month, printed totals ...
    log: ParseLog


@dataclass
class EsicEcrDocument:
    members: list[EsicEcrMember]
    header: dict
    log: ParseLog


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@dataclass
class NameComparison:
    verdict: NameVerdict
    explanation: str              # human readable, e.g. "first name RENU differs from REKHA"
    compared_with: str = ""       # the ECR name that gave the best result


@dataclass
class CheckResult:
    """Verdict of one employee against one ECR (PF or ESIC)."""

    status: Status
    reason: str
    needs_review: bool = False
    identifier: Optional[str] = None
    ecr_name: str = ""
    wagesheet_amount: Optional[float] = None
    ecr_amount: Optional[float] = None
    difference: Optional[float] = None        # ECR - wagesheet (negative = short deposit)
    expected_from_ecr_wages: Optional[float] = None
    name_verdict: Optional[NameVerdict] = None
    ecr_page: Optional[int] = None


@dataclass
class EmployeeResult:
    row: WagesheetRow
    pf: CheckResult
    esic: CheckResult


@dataclass
class EcrOnlyMember:
    """A member present in an ECR but absent from the wagesheet."""

    check: str          # "PF" or "ESIC"
    identifier: str
    name: str
    amount: Optional[float]
    page: int


@dataclass
class ReconciliationCheck:
    """Parsed totals vs totals printed on the ECR."""

    document: str
    metric: str
    printed_value: Optional[float]
    parsed_value: float
    ok: bool
    note: str = ""


@dataclass
class VerificationReport:
    employees: list[EmployeeResult]
    ecr_only: list[EcrOnlyMember]
    reconciliation: list[ReconciliationCheck]
    warnings: list[str]
    metadata: dict
    pf_log: ParseLog
    esic_log: ParseLog

    def summary(self) -> dict:
        """Counts per status for PF and ESIC, plus money at risk."""
        return {
            "total_employees": len(self.employees),
            "pf": _summarise([e.pf for e in self.employees]),
            "esic": _summarise([e.esic for e in self.employees]),
            "ecr_only": {
                "pf": sum(1 for m in self.ecr_only if m.check == "PF"),
                "esic": sum(1 for m in self.ecr_only if m.check == "ESIC"),
            },
            "reconciliation_ok": all(r.ok for r in self.reconciliation),
        }


def _summarise(results: list[CheckResult]) -> dict:
    counts = {status.value: 0 for status in Status}
    for result in results:
        counts[result.status.value] += 1
    total = len(results)
    short_deposit = sum(
        -r.difference for r in results
        if r.status == Status.AMOUNT_MISMATCH and r.difference is not None and r.difference < 0
    )
    return {
        "counts": counts,
        "needs_review": sum(1 for r in results if r.needs_review),
        "total": total,
        "match_rate": round(100 * counts[Status.MATCHED.value] / total, 1) if total else 0.0,
        "short_deposit_amount": round(short_deposit, 2),
    }
