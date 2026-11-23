"""
Format-free parser for the scanning machine's text overlay.

Input: the overlay as text rows (from OCR, or from Gemini's read). Output: OverlayFields.

It does not assume one layout. It finds every "key: value" pair in each row, maps the
key through the aliases in rules.py, and parses the value with its unit. Formats seen
in the sample frames, all handled here:

    AWB No: 19108610906662          AWB_NO :77873372404        Barcode:19108610817924
    L: 39   W: 28.5 cm   H: 29 cm   Length: 35.900 cm          LENGTH(cm) : 21.40
    Dimension: 0208 X 0148 X 0163   Dimension:L0213XH0148XW0178
    A.W: 2320 g   Weight: 2210.000 gm   WEIGHT(Kg) : 0.58   Weight:01190
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.case_study_1 import rules
from app.case_study_1.models import Dimensions, Measure, OverlayFields

NUMBER = r"[-+]?\d+(?:[.,]\d+)?"
# A key starts with a letter, at the start of the row or after a space, and ends at ":".
KEY_PATTERN = re.compile(r"(?:(?<=\s)|^)([A-Za-z][A-Za-z0-9 ._()/#-]{0,30}?)\s*[:：]")
KEY_UNIT_PATTERN = re.compile(r"\(([A-Za-z]+)\)")
LENGTH_UNIT_PATTERN = re.compile(r"(?i)(?<![a-z])(mm|cm|inches|inch|in|m)(?![a-z])")
VALUE_WITH_UNIT = re.compile(rf"({NUMBER})\s*([A-Za-z]+)?")

_ALIAS_TO_FIELD = {alias: field for field, aliases in rules.FIELD_ALIASES.items() for alias in aliases}


# ---------------------------------------------------------------- small helpers

def squash(text: str) -> str:
    """'AWB_No' -> 'awbno', 'A.W' -> 'aw'. Used to compare key names."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def split_key(raw_key: str) -> tuple[str, Optional[str]]:
    """'LENGTH(cm)' -> ('length', 'cm'); 'AWB_No' -> ('awbno', None)."""
    unit_match = KEY_UNIT_PATTERN.search(raw_key)
    unit = unit_match.group(1).lower() if unit_match else None
    return squash(KEY_UNIT_PATTERN.sub("", raw_key)), unit


def field_for_key(squashed_key: str) -> Optional[str]:
    return _ALIAS_TO_FIELD.get(squashed_key)


def to_number(text: str) -> float:
    return float(text.replace(",", "."))


def normalise_awb(text: Optional[str]) -> Optional[str]:
    """Remove spaces and dashes, upper-case, and check the format. None if it is not a valid AWB."""
    if not text:
        return None
    candidate = re.sub(r"[\s\-]", "", str(text)).upper()
    return candidate if re.match(rules.AWB_PATTERN, candidate) else None


def pick_awb(value: str) -> Optional[str]:
    """
    The AWB in a value. OCR sometimes adds a stray character ("1 19108193959674"): when exactly
    one token is a valid AWB, that token is used. Tokens are never joined (that could invent a number).
    """
    valid = [awb for awb in (normalise_awb(token) for token in value.split()) if awb]
    return valid[0] if len(valid) == 1 else None


# ---------------------------------------------------------------- rows -> key/value pairs

def split_pairs(row: str) -> list[tuple[str, str]]:
    """
    'L:39 A.W:2320g' -> [('L', '39'), ('A.W', '2320g')].
    When a matched key is not known but ends with known words ('ITG AWB_NO'), the leading
    words are given back to the previous value.
    """
    matches = list(KEY_PATTERN.finditer(row))
    pairs: list[list[str]] = []
    for i, match in enumerate(matches):
        key = match.group(1).strip()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(row)
        value = row[match.end():value_end].strip()
        key, spill = _trim_unknown_prefix(key)
        if spill and pairs:
            pairs[-1][1] = f"{pairs[-1][1]} {spill}".strip()
        pairs.append([key, value])
    return [(k, v) for k, v in pairs]


# Generic keys a longer unknown key may not be trimmed to ("Tracking ID" must not become "ID").
NOT_TRIMMED_TO = {"id", "l", "w", "h", "b", "date", "time", "size"}


def _trim_unknown_prefix(key: str) -> tuple[str, str]:
    words = key.split()
    if field_for_key(split_key(key)[0]):
        return key, ""
    for start in range(1, len(words)):
        candidate = " ".join(words[start:])
        squashed = split_key(candidate)[0]
        if squashed not in NOT_TRIMMED_TO and field_for_key(squashed):
            return candidate, " ".join(words[:start])
    return key, ""


# ---------------------------------------------------------------- value parsers

def parse_length(text: str, key_unit: Optional[str] = None) -> Optional[tuple[float, Optional[str], str]]:
    """'28.5cm' -> (28.5, 'cm', '28.5cm'). The number is NOT converted yet (unit may be shared)."""
    match = VALUE_WITH_UNIT.search(text)
    if not match:
        return None
    unit = key_unit or (match.group(2) or "").lower() or None
    if unit and unit not in rules.LENGTH_UNITS_TO_CM:
        unit = None
    return to_number(match.group(1)), unit, text.strip()


def _infer_length_unit(raw_numbers: list[str], values: list[float]) -> str:
    """No unit printed: zero-padded 4-digit integers or values above 250 are mm, otherwise cm."""
    padded = all(re.fullmatch(r"0\d{%d}" % (rules.DIMENSION_MM_PADDED_DIGITS - 1), n) for n in raw_numbers)
    if padded or max(values) > rules.DIMENSION_RANGE_CM[1]:
        return "mm"
    return "cm"


def build_dimensions(parts: list[tuple[float, Optional[str], str]], raw_numbers: list[str]) -> Dimensions:
    """parts = (number, unit or None, as printed) for L, W, H. Shares a unit printed on any part."""
    units = {unit for _, unit, _ in parts if unit}
    inferred = not units
    unit = units.pop() if len(units) == 1 else (_infer_length_unit(raw_numbers, [p[0] for p in parts]) if inferred else "cm")
    factor = rules.LENGTH_UNITS_TO_CM[unit]
    measures = [Measure(round(number * factor, 2), printed, unit, inferred)
                for number, _, printed in parts]
    return Dimensions(*measures)


def parse_dimensions_text(text: str, key_unit: Optional[str] = None) -> Optional[Dimensions]:
    """
    '0208 X 0148 X 0163'      -> 20.8 x 14.8 x 16.3 cm (unit inferred: mm)
    'L0213XH0148XW0178'       -> L 21.3, W 17.8, H 14.8 cm (letters give the order)
    '39 x 28.5 x 29 cm'       -> 39 x 28.5 x 29 cm
    """
    unit_match = LENGTH_UNIT_PATTERN.search(text)
    unit = key_unit or (unit_match.group(1).lower() if unit_match else None)
    body = LENGTH_UNIT_PATTERN.sub(" ", text)
    pieces = [p.strip() for p in re.split(r"\s*[xX*×]\s*", body.strip()) if p.strip()]
    if len(pieces) != 3:
        return None
    lettered: dict[str, str] = {}
    numbers: list[str] = []
    for piece in pieces:
        match = re.fullmatch(rf"([LWHBlwhb])?\s*:?\s*({NUMBER})", piece)
        if not match:
            return None
        numbers.append(match.group(2))
        if match.group(1):
            lettered[match.group(1).upper().replace("B", "W")] = match.group(2)
    if len(lettered) == 3 and set(lettered) == {"L", "W", "H"}:
        numbers = [lettered["L"], lettered["W"], lettered["H"]]
    parts = [(to_number(n), unit, text.strip()) for n in numbers]
    return build_dimensions(parts, numbers)


def parse_weight(text: str, key_unit: Optional[str] = None) -> Optional[Measure]:
    """'2210.000 gm' -> 2.21 kg; '0.58' with key unit Kg -> 0.58 kg; '01190' -> 1.19 kg (inferred grams)."""
    match = VALUE_WITH_UNIT.search(text)
    if not match:
        return None
    raw, number = match.group(1), to_number(match.group(1))
    unit = key_unit or (match.group(2) or "").lower() or None
    if unit and unit not in rules.WEIGHT_UNITS_TO_KG:
        unit = None
    inferred = unit is None
    if inferred:
        is_integer = not re.search(r"[.,]", raw)
        unit = "g" if is_integer and number >= rules.WEIGHT_GRAMS_IF_INTEGER_AT_LEAST else "kg"
    return Measure(round(number * rules.WEIGHT_UNITS_TO_KG[unit], 3), text.strip(), unit, inferred)


def first_number(text: str) -> Optional[float]:
    match = re.search(NUMBER, text)
    return to_number(match.group(0)) if match else None


# ---------------------------------------------------------------- whole overlay

def parse_overlay(rows: list[str]) -> OverlayFields:
    """Turn overlay text rows into fields. Unknown keys are ignored."""
    fields = OverlayFields()
    separate: dict[str, tuple[float, Optional[str], str]] = {}
    separate_raw: dict[str, str] = {}
    awbs: dict[str, str] = {}
    pending_key: Optional[tuple[str, Optional[str]]] = None

    for row in rows:
        row = unicodedata.normalize("NFKC", row)          # OCR sometimes returns full-width "（" or "："
        pairs = split_pairs(row)
        if not pairs and pending_key:                    # value printed on the row below its key
            pairs, pending_key = [(pending_key[0], row)], None
        for raw_key, value in pairs:
            key, key_unit = split_key(raw_key)
            field = field_for_key(key)
            if not field:
                continue
            if not value:
                pending_key = (raw_key, key_unit)
                continue
            if field == "awb":
                awb = pick_awb(value)
                if awb:
                    awbs.setdefault(awb, value)
                else:
                    fields.problems.append(f"AWB not in a valid format: '{value}'")
            elif field in ("length", "width", "height"):
                parsed = parse_length(value, key_unit)
                if parsed:
                    separate[field] = parsed
                    separate_raw[field] = re.search(NUMBER, value).group(0)
            elif field == "dimensions":
                fields.dimensions = parse_dimensions_text(value, key_unit) or fields.dimensions
                if fields.dimensions is None:
                    fields.problems.append(f"dimensions not understood: '{value}'")
            elif field == "weight":
                fields.weight = parse_weight(value, key_unit) or fields.weight
            elif field == "volume":
                fields.volume_raw, fields.volume_as_printed = first_number(value), value
            elif field == "volumetric":
                fields.volumetric_raw, fields.volumetric_as_printed = first_number(value), value
            elif field in ("location", "scan_time", "machine_id") and getattr(fields, field) is None:
                setattr(fields, field, value)      # first one wins: the overlay is printed before label text

    if len(separate) == 3 and fields.dimensions is None:
        order = ["length", "width", "height"]
        fields.dimensions = build_dimensions([separate[k] for k in order], [separate_raw[k] for k in order])
    elif separate and fields.dimensions is None:
        fields.problems.append("only some of length / width / height are printed")

    if len(awbs) > 1:
        fields.problems.append("different AWB numbers printed: " + ", ".join(awbs))
    if awbs:
        fields.awb, fields.awb_as_printed = next(iter(awbs.items()))
    return fields


# ---------------------------------------------------------------- two OCR passes

def is_complete(fields: OverlayFields) -> bool:
    return bool(fields.awb and fields.dimensions and not fields.problems)


def merge_passes(first: OverlayFields, second: OverlayFields) -> OverlayFields:
    """
    Combine two OCR passes of the same frame. A field read by only one pass is taken from it;
    a field read differently by the two passes becomes a problem (sent to review).
    """
    merged = OverlayFields()
    conflicts = []
    for name in ("awb", "awb_as_printed", "dimensions", "weight", "volume_raw", "volume_as_printed",
                 "volumetric_raw", "volumetric_as_printed", "location", "scan_time", "machine_id"):
        a, b = getattr(first, name), getattr(second, name)
        setattr(merged, name, a if a is not None else b)
    if first.awb and second.awb and first.awb != second.awb:
        conflicts.append(f"two OCR passes read different AWBs ({first.awb}, {second.awb})")
    if first.dimensions and second.dimensions and any(
            abs(x - y) > rules.DIMENSION_AGREEMENT_CM for x, y in zip(first.dimensions.as_cm(), second.dimensions.as_cm())):
        conflicts.append("two OCR passes read different dimensions")
    if first.weight and second.weight and abs(first.weight.value - second.weight.value) > rules.WEIGHT_AGREEMENT_KG:
        conflicts.append("two OCR passes read different weights")
    unresolved = [p for p in dict.fromkeys(first.problems + second.problems) if not _resolved(p, merged)]
    merged.problems = conflicts + unresolved
    return merged


def _resolved(problem: str, merged: OverlayFields) -> bool:
    if problem.startswith(("only some of", "dimensions not understood")):
        return merged.dimensions is not None
    if problem.startswith("AWB not in a valid format"):
        return merged.awb is not None
    return False
