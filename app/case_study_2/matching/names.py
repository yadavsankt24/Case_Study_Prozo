"""
Name matching: decide whether two names refer to the same person.

Why not a single fuzzy-similarity score?
    "SUNITA DEVI"  vs "SUNEETA DEVI"    -> similarity 87, SAME person
    "RENU SHARMA"  vs "REKHA SHARMA"    -> similarity 78, DIFFERENT person
    "KUMAR ANIL"   vs "ANIL KUMAR"      -> similarity 50, SAME person
No single threshold separates these. Instead we compare the names
word by word, with explicit, explainable rules.

Word-level comparison (strongest first):
    EXACT     identical after cleaning              RAJESH  = RAJESH
    PHONETIC  same canonical spelling               SUNEETA ~ SUNITA, PRASHAD ~ PRASAD
    INITIAL   one word is the initial of the other  R       ~ RAJESH        (needs review)
    VOWEL     same consonants and first letter      SITA    ~ SEETA-like    (needs review)
    NONE      anything else                         RAKESH  x RAMESH, REKHA x RENU

Name-level decision:
    MATCH     every word of the shorter name pairs with EXACT/PHONETIC, nothing extra
    PROBABLE  every word pairs, but via INITIAL/VOWEL or the longer name has extra words
    CONFLICT  at least one word of the shorter name has no partner -> a different name

Tolerance in one sentence: spelling, spacing, word order, titles and initials
are tolerated; a different given name or surname is never tolerated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from app.case_study_2 import rules
from app.case_study_2.matching.normalize import consonant_skeleton, name_tokens, phonetic_key
from app.case_study_2.models import NameComparison, NameVerdict


class WordMatch(IntEnum):
    NONE = 0
    VOWEL = 1
    INITIAL = 2
    PHONETIC = 3
    EXACT = 4


@dataclass(frozen=True)
class _Pair:
    left: str
    right: str
    level: WordMatch


def compare_words(left: str, right: str) -> WordMatch:
    """Compare two single (already cleaned) name words."""
    if left == right:
        return WordMatch.EXACT
    if phonetic_key(left) == phonetic_key(right):
        return WordMatch.PHONETIC
    if rules.ALLOW_INITIALS and _is_initial_of(left, right):
        return WordMatch.INITIAL
    if rules.ALLOW_VOWEL_VARIANTS and min(len(left), len(right)) >= 3:
        if consonant_skeleton(left) == consonant_skeleton(right):
            return WordMatch.VOWEL
    return WordMatch.NONE


def _is_initial_of(a: str, b: str) -> bool:
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) == 1 and len(long_) > 1 and long_.startswith(short)


class NameMatcher:
    """Stateless; one instance can be shared across threads."""

    def compare(self, wagesheet_name: str, ecr_name: str) -> NameComparison:
        ws_words = name_tokens(wagesheet_name)
        ecr_words = name_tokens(ecr_name)

        if not ws_words:
            return NameComparison(NameVerdict.CONFLICT, "name is blank in the wagesheet", ecr_name)
        if not ecr_words:
            return NameComparison(NameVerdict.CONFLICT, "name is blank in the ECR", ecr_name)

        # Fast paths that need no word pairing.
        if ws_words == ecr_words:
            return NameComparison(NameVerdict.MATCH, "exact match", ecr_name)
        if sorted(ws_words) == sorted(ecr_words):
            return NameComparison(NameVerdict.MATCH, "same name, different word order", ecr_name)

        result = self._compare_word_by_word(ws_words, ecr_words, ecr_name)

        # "RAJ KUMAR" vs "RAJKUMAR": words differ only because of a missing space.
        if result.verdict == NameVerdict.CONFLICT and \
                phonetic_key("".join(ws_words)) == phonetic_key("".join(ecr_words)):
            return NameComparison(NameVerdict.MATCH, "same name, different spacing", ecr_name)
        return result

    def compare_best(self, wagesheet_name: str, ecr_names: list[str]) -> NameComparison:
        """
        Compare against several ECR names (the PF ECR carries both the
        'name as per ECR' and the 'name as per UAN repository') and keep the best.
        """
        candidates = [n for n in ecr_names if n and n.strip()]
        if not candidates:
            return NameComparison(NameVerdict.CONFLICT, "name is blank in the ECR", "")
        results = [self.compare(wagesheet_name, name) for name in candidates]
        rank = {NameVerdict.MATCH: 2, NameVerdict.PROBABLE: 1, NameVerdict.CONFLICT: 0}
        return max(results, key=lambda r: rank[r.verdict])

    # ------------------------------------------------------------------ #

    def _compare_word_by_word(self, ws_words: list[str], ecr_words: list[str], ecr_name: str) -> NameComparison:
        pairs = _pair_words(ws_words, ecr_words)
        paired_ws = {p.left for p in pairs}
        paired_ecr = {p.right for p in pairs}
        unpaired_ws = [w for w in ws_words if w not in paired_ws]
        unpaired_ecr = [w for w in ecr_words if w not in paired_ecr]

        shorter_unpaired = unpaired_ws if len(ws_words) <= len(ecr_words) else unpaired_ecr
        if shorter_unpaired:
            return NameComparison(NameVerdict.CONFLICT, _conflict_text(unpaired_ws, unpaired_ecr), ecr_name)

        notes = []
        for pair in pairs:
            if pair.level == WordMatch.PHONETIC:
                notes.append(f"spelling variant {pair.left}~{pair.right}")
            elif pair.level == WordMatch.INITIAL:
                notes.append(f"initial {pair.left}~{pair.right}")
            elif pair.level == WordMatch.VOWEL:
                notes.append(f"vowel difference {pair.left}~{pair.right}")
        if unpaired_ws:
            notes.append(f"extra name part {' '.join(unpaired_ws)} in wagesheet")
        if unpaired_ecr:
            notes.append(f"extra name part {' '.join(unpaired_ecr)} in ECR")

        weak = any(p.level in (WordMatch.INITIAL, WordMatch.VOWEL) for p in pairs)
        verdict = NameVerdict.PROBABLE if (weak or unpaired_ws or unpaired_ecr) else NameVerdict.MATCH
        return NameComparison(verdict, "; ".join(notes) or "match", ecr_name)


def _pair_words(left_words: list[str], right_words: list[str]) -> list[_Pair]:
    """
    Greedy one-to-one pairing: strongest word matches are taken first.
    Names have 1-5 words, so trying all pairs is cheap and easy to follow.
    """
    candidates = [
        _Pair(l, r, compare_words(l, r))
        for l in left_words
        for r in right_words
    ]
    candidates = [c for c in candidates if c.level > WordMatch.NONE]
    candidates.sort(key=lambda c: c.level, reverse=True)

    used_left: set[int] = set()
    used_right: set[int] = set()
    pairs: list[_Pair] = []
    for cand in candidates:
        li, ri = _first_free(left_words, cand.left, used_left), _first_free(right_words, cand.right, used_right)
        if li is None or ri is None:
            continue
        used_left.add(li)
        used_right.add(ri)
        pairs.append(cand)
    return pairs


def _first_free(words: list[str], word: str, used: set[int]) -> int | None:
    for index, w in enumerate(words):
        if w == word and index not in used:
            return index
    return None


def _conflict_text(unpaired_ws: list[str], unpaired_ecr: list[str]) -> str:
    ws = " ".join(unpaired_ws) or "-"
    ecr = " ".join(unpaired_ecr) or "-"
    return f"name part differs: wagesheet has {ws}, ECR has {ecr}"
