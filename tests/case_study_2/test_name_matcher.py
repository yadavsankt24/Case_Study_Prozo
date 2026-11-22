"""The name-matching tolerance, written down as executable examples."""

from __future__ import annotations

import pytest

from app.case_study_2.matching.names import NameMatcher
from app.case_study_2.models import NameVerdict

MATCH, PROBABLE, CONFLICT = NameVerdict.MATCH, NameVerdict.PROBABLE, NameVerdict.CONFLICT

CASES = [
    # --- tolerated: same person -------------------------------------------
    ("ANIL KUMAR", "ANIL KUMAR", MATCH),
    ("anil  kumar", "ANIL KUMAR", MATCH),                 # case / spacing
    ("Smt. Sunita Devi", "SUNITA DEVI", MATCH),           # title
    ("KUMAR ANIL", "ANIL KUMAR", MATCH),                  # word order
    ("SUNITA DEVI", "SUNEETA DEVI", MATCH),               # ee / i
    ("POOJA GUPTA", "PUJA GUPTHA", MATCH),                # oo / u, th / t
    ("PRASAD", "PRASHAD", MATCH),                         # sh / s
    ("MOHD IRFAN", "MOHAMMED IRFAN", MATCH),              # known alias
    ("RAJ KUMAR", "RAJKUMAR", MATCH),                     # missing space
    ("LAXMI JAIN", "LAKSHMI JAIN", MATCH),                # x / ksh
    ("VIJAY", "VIJAI", MATCH),                            # y / i
    # --- probably the same person: matched but flagged for review ----------
    ("R KUMAR", "RAJESH KUMAR", PROBABLE),                # initial
    ("ANIL KUMAR", "ANIL KUMAR SINGH", PROBABLE),         # extra name part
    ("KIRAN", "KARAN", PROBABLE),                         # vowel-only difference (known limitation)
    # --- never tolerated: different person ---------------------------------
    ("DINESH PRASAD", "DEVENDRA PRASAD", CONFLICT),       # sample data trap (PF)
    ("REKHA SHARMA", "RENU SHARMA", CONFLICT),            # sample data trap (ESIC)
    ("RAKESH VERMA", "RAMESH VERMA", CONFLICT),           # one consonant differs
    ("SUNIL", "SUSHIL", CONFLICT),
    ("ASHA RANI", "USHA RANI", CONFLICT),                 # first letter differs
    ("PRIYA SINGH", "PRIYANKA SINGH", CONFLICT),
    ("ANIL KUMAR", "ANIL VERMA", CONFLICT),               # surname differs
    ("ANIL KUMAR", "", CONFLICT),                         # blank ECR name
]


@pytest.mark.parametrize("wagesheet_name, ecr_name, expected", CASES)
def test_name_matching_tolerance(wagesheet_name, ecr_name, expected):
    assert NameMatcher().compare(wagesheet_name, ecr_name).verdict == expected


def test_conflict_explains_which_part_differs():
    result = NameMatcher().compare("REKHA SHARMA", "RENU SHARMA")
    assert "REKHA" in result.explanation and "RENU" in result.explanation


def test_best_of_two_ecr_names_is_used():
    # PF ECR carries 'name as per ECR' and 'name as per UAN repository'
    result = NameMatcher().compare_best("SUNITA DEVI", ["S DEVI", "SUNITA DEVI"])
    assert result.verdict == MATCH
