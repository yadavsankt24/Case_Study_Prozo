"""
Case Study 2 business rules: wagesheet vs PF / ESIC ECR verification.

This is the ONE file to edit when the compliance team changes a rule
(tolerance, rates, accepted column names, name-matching strictness).
Keeping these values together makes rule changes safe and reviewable.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Contribution rates (employee share)
# ---------------------------------------------------------------------------
PF_EMPLOYEE_RATE = 0.12      # EPF employee share, 12% of EPF wages
ESIC_EMPLOYEE_RATE = 0.0075  # ESIC employee (IP) share, 0.75% of gross wages

# ---------------------------------------------------------------------------
# Amount comparison
# ---------------------------------------------------------------------------
# Wagesheet amount vs deposited amount may differ by rounding only.
# PF rounds to the nearest rupee; ESIC rounds up to the next rupee.
AMOUNT_TOLERANCE_RUPEES = 1.0

# Tolerance used when reconciling our parsed totals with the totals printed
# in the ECR header. A larger gap means rows were probably missed while parsing.
RECONCILIATION_TOLERANCE_RUPEES = 1.0

# ---------------------------------------------------------------------------
# Identifier formats
# ---------------------------------------------------------------------------
UAN_LENGTH = 12        # EPFO Universal Account Number
IP_NUMBER_LENGTH = 10  # ESIC Insurance Person number

# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------
# Words that are honorifics, not part of the person's name.
# NOTE: KUMAR / KUMARI / DEVI are deliberately NOT here: they are real name parts.
NAME_TITLES = {"MR", "MRS", "MS", "MISS", "SMT", "SHRI", "SH", "SHREE", "KM", "KUM", "DR", "LATE"}

# Spellings that refer to the same name. Left side is normalised to the right side.
NAME_ALIASES = {
    "MOHD": "MOHAMMAD",
    "MD": "MOHAMMAD",
    "MOHAMAD": "MOHAMMAD",
    "MOHAMMED": "MOHAMMAD",
    "MUHAMMAD": "MOHAMMAD",
    "MOHAMED": "MOHAMMAD",
    "MOHAMMAD": "MOHAMMAD",
}

# If True, an initial ("R") may stand in for a full given name ("RAJESH").
# Such matches are always marked "needs review".
ALLOW_INITIALS = True

# If True, names whose consonants are identical and whose first letter is the
# same (e.g. SITA / SEETA, RAM / RAMA) are accepted as "probable" matches and
# marked "needs review". Names that differ by a consonant (RAKESH / RAMESH,
# REKHA / RENU) are always a mismatch.
ALLOW_VOWEL_VARIANTS = True

# ---------------------------------------------------------------------------
# Wagesheet columns
# ---------------------------------------------------------------------------
# Header names are compared after removing everything except letters/digits,
# so "ESIC @ 0.75%" and "esic 0.75" are the same. Add new vendor spellings here.
WAGESHEET_COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["Name", "Employee Name", "Emp Name", "Name of Employee", "Member Name", "Worker Name"],
    "uan": ["UAN", "UAN No", "UAN Number", "PF UAN", "UAN No."],
    "ip_number": ["IP Number", "IP No", "ESIC No", "ESIC Number", "ESIC IP No", "ESIC IP Number", "Insurance No"],
    "agency": ["Agency", "Vendor", "Contractor", "Agency Name", "Vendor Name"],
    "state": ["State", "Location", "Work State"],
    "esic_amount": ["ESIC @ 0.75%", "ESIC 0.75%", "ESI (0.75%)", "ESIC", "ESI", "Employee ESIC", "ESIC Deduction", "ESI Ded"],
    "pf_amount": ["PF @ 12%", "PF 12%", "EPF (12%)", "PF", "EPF", "Employee PF", "PF Deduction", "EPF Ded"],
}

REQUIRED_WAGESHEET_COLUMNS = ["name", "pf_amount", "esic_amount"]
# At least one identifier column must be present.
IDENTIFIER_WAGESHEET_COLUMNS = ["uan", "ip_number"]
