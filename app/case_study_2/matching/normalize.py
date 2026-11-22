"""
Normalisation helpers for identifiers, amounts and names.

Real vendor files are messy: Excel turns UANs into floats or scientific
notation, people type spaces inside numbers, and names come with titles and
punctuation. Everything is cleaned here *before* any comparison happens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.case_study_2.rules import NAME_ALIASES, NAME_TITLES

_SCIENTIFIC_NOTATION = re.compile(r"^\d(\.\d+)?E\+?\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class IdentifierResult:
    value: Optional[str]  # cleaned identifier, or None if unusable
    issue: str = ""       # explanation when value is None


def normalize_identifier(raw: object, expected_length: int, label: str) -> IdentifierResult:
    """
    Clean a UAN / IP number coming from Excel or a PDF.

    Handles: integers, floats like 999912340001.0, strings with spaces or
    dashes, and detects scientific notation (e.g. "9.99912E+11") where Excel
    has already destroyed the trailing digits.
    """
    if raw is None:
        return IdentifierResult(None, f"{label} is blank in the wagesheet")

    if isinstance(raw, float):
        if not raw.is_integer():
            return IdentifierResult(None, f"{label} '{raw}' is not a whole number")
        text = str(int(raw))
    else:
        text = str(raw).strip()

    if not text:
        return IdentifierResult(None, f"{label} is blank in the wagesheet")

    if _SCIENTIFIC_NOTATION.match(text.replace(" ", "")):
        return IdentifierResult(
            None,
            f"{label} '{text}' was converted to scientific notation by Excel and its digits are lost",
        )

    if text.endswith(".0"):  # "999912340001.0" stored as text
        text = text[:-2]

    digits = re.sub(r"[\s\-]", "", text)
    if not digits.isdigit():
        return IdentifierResult(None, f"{label} '{text}' contains non-numeric characters")
    if len(digits) != expected_length:
        return IdentifierResult(None, f"{label} '{text}' has {len(digits)} digits (expected {expected_length})")
    return IdentifierResult(digits)


def parse_amount(raw: object) -> Optional[float]:
    """Convert '1,622', '102.00', 1622 or None into a float (None if not a number)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "").replace("₹", "")
    if text in {"", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def name_tokens(raw: str) -> list[str]:
    """
    Split a name into comparable words.

    "Smt. Sunita  devi" -> ["SUNITA", "DEVI"]
    "MOHD. IRFAN"       -> ["MOHAMMAD", "IRFAN"]
    """
    if not raw:
        return []
    cleaned = re.sub(r"[^A-Za-z ]", " ", str(raw)).upper()
    tokens = [t for t in cleaned.split() if t not in NAME_TITLES]
    return [NAME_ALIASES.get(t, t) for t in tokens]


# Ordered rules that remove common Indian transliteration differences.
# Applied identically to both names, so they only make *equal-sounding*
# spellings equal (SUNEETA -> SUNITA, PRASHAD -> PRASAD, GUPTHA -> GUPTA).
_PHONETIC_RULES: list[tuple[str, str]] = [
    ("EE", "I"),
    ("OO", "U"),
    ("PH", "F"),
    ("SH", "S"),
    ("TH", "T"),
    ("DH", "D"),
    ("BH", "B"),
    ("KH", "K"),
    ("GH", "G"),
    ("CH", "C"),
    ("W", "V"),
    ("Z", "J"),
    ("Q", "K"),
    ("Y", "I"),
    ("X", "KS"),   # LAXMI ~ LAKSHMI (found by the synthetic evaluation)
]


def phonetic_key(token: str) -> str:
    """Canonical spelling of a single name word (see _PHONETIC_RULES)."""
    key = token.upper()
    for pattern, replacement in _PHONETIC_RULES:
        key = key.replace(pattern, replacement)
    # collapse doubled letters: "AA" -> "A", "NN" -> "N"
    key = re.sub(r"(.)\1+", r"\1", key)
    return key


def consonant_skeleton(token: str) -> str:
    """Phonetic key without vowels: SITA -> ST, SEETA -> ST, RAKESH -> RKS, RAMESH -> RMS."""
    key = phonetic_key(token)
    return key[0] + re.sub(r"[AEIOU]", "", key[1:]) if key else ""
