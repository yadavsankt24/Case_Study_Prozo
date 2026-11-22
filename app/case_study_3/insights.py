"""
Plain-language insight for each flagged FC-day.

The template writer is always used first: it states the deviation, every
breached line, the top contributors by rupee impact and a recommended action,
e.g.

    On 27 May 2025, CM2 = 10.1% (Red: 4.9 pts below the 15% target).
    Top contributors: Power & Fuel 15.2% (max 12%, ₹3,410 over), Manpower 32.8%
    (max 27%, ₹5,940 over). Recommend: cost audit - check power bills and
    DG-set running hours; review shift rosters and overtime against order volume.

An optional LLM (Gemini free tier / Ollama) can re-phrase the text for the
daily digest. Its output is used only if every number it states also appears
in the template facts; otherwise the template text is kept.
"""

from __future__ import annotations

import re
from typing import Optional

from app.shared.llm import LLMClient, NoLLM
from app.case_study_3 import rules
from app.case_study_3.models import Anomaly, Colour, DayResult, Severity, Trend


def rupees(value: float) -> str:
    return f"₹{value:,.0f}"


def pct(value: float, limit: Optional[float] = None) -> str:
    """1 decimal, or 2 when 1 decimal would print the limit itself (14.98% must not read as 15.0%)."""
    text = f"{value:.1f}"
    if limit is not None and abs(float(text) - limit) < 1e-9 and abs(value - limit) > 1e-9:
        text = f"{value:.2f}"
    return text + "%"


def write_insight(day: DayResult) -> tuple[str, str]:
    """Return (insight sentence(s), recommended action) for one FC-day."""
    if day.is_clean:
        return (f"On {day.day:%d %b %Y}, all cost lines are within target. CM1 {day.cm1_pct:.1f}%, "
                f"CM2 {day.cm2_pct:.1f}% ({day.colour.value}). No action needed."), "none"

    open_items = day.open_anomalies
    if not open_items:
        return (f"On {day.day:%d %b %Y}, CM2 = {day.cm2_pct:.1f}% ({day.colour.value}). "
                f"All flags on this day are marked as known issues."), "none"

    parts = [f"On {day.day:%d %b %Y}, {_headline(day)}."]
    costs = [a for a in open_items if a.line_item not in ("CM1 %", "CM2 %")]
    above = sorted([a for a in costs if a.status == "Above max"], key=lambda a: -a.impact_rupees)
    below = [a for a in costs if a.status == "Below min"]
    cm1 = next((a for a in open_items if a.line_item == "CM1 %"), None)

    if cm1:
        parts.append(f"CM1 = {day.cm1_pct:.1f}% ({cm1.deviation_pts:.1f} pts {'below' if cm1.status == 'Below target' else 'above'} "
                     f"the {rules.CM1_TARGET[0]:g}-{rules.CM1_TARGET[1]:g}% target).")
    if above:
        parts.append("Top contributors: " + ", ".join(
            f"{a.line_item} {pct(a.pct_of_revenue, _limits(a)[1])} (max {a.target_range.split('-')[1]}, "
            f"{rupees(a.impact_rupees)} over)"
            for a in above[:rules.TOP_CONTRIBUTORS_IN_DIGEST]) + ".")
        if len(above) > rules.TOP_CONTRIBUTORS_IN_DIGEST:
            parts.append(f"{len(above) - rules.TOP_CONTRIBUTORS_IN_DIGEST} more line(s) slightly above max.")
    if below:
        parts.append("Below min: " + ", ".join(
            f"{a.line_item} {pct(a.pct_of_revenue, _limits(a)[0])} (min {a.target_range.split('-')[0]}%)"
            for a in below) + ".")

    action = recommend(day, above, below)
    parts.append(f"Recommend: {action}.")
    return " ".join(parts), action


def _limits(anomaly: Anomaly) -> tuple[float, float]:
    low, high = anomaly.target_range.rstrip("%").split("-")
    return float(low), float(high)


def _headline(day: DayResult) -> str:
    low, high = rules.CM2_TARGET
    if day.colour == Colour.RED:
        return (f"CM2 = {day.cm2_pct:.1f}% (Red: below the {rules.RED_BELOW:g}% threshold, "
                f"{low - day.cm2_pct:.1f} pts under the {low:g}% target)")
    if day.colour == Colour.BLUE:
        return f"CM2 = {day.cm2_pct:.1f}% (Blue: suspiciously high, {day.cm2_pct - high:.1f} pts above the {high:g}% max)"
    if day.colour == Colour.YELLOW:
        side = f"{low - day.cm2_pct:.1f} pts below the {low:g}%" if day.cm2_pct < low else f"{day.cm2_pct - high:.1f} pts above the {high:g}%"
        return f"CM2 = {day.cm2_pct:.1f}% (Yellow: {side} target)"
    return f"CM2 = {day.cm2_pct:.1f}% (Green: within target)"


def recommend(day: DayResult, above: list[Anomaly], below: list[Anomaly]) -> str:
    if day.colour == Colour.BLUE:
        return rules.ACTION_BLUE
    steps = [rules.ACTION_ABOVE_MAX[a.line_item] for a in above[:2]]
    if below and not above:
        steps.append(rules.ACTION_BELOW_MIN + f" for {', '.join(a.line_item for a in below)}")
    text = "; ".join(steps) if steps else "monitor"
    return f"{rules.ACTION_RED} - {text}" if day.colour == Colour.RED else text


def trend_sentence(trend: Trend) -> str:
    bits = []
    if trend.streak_colour and trend.streak_days >= 2:
        bits.append(f"{trend.streak_days} {trend.streak_colour.value} days in a row")
    if trend.avg_cm2_7d is not None:
        bits.append(f"7-day average CM2 {trend.avg_cm2_7d:.1f}%")
    if trend.prev_cm2 is not None:
        bits.append(f"previous day {trend.prev_cm2:.1f}%")
    return ("Trend: " + ", ".join(bits) + ".") if bits else ""


# ---------------------------------------------------------------------------
# Optional LLM phrasing (digest only)
# ---------------------------------------------------------------------------

def polish_with_llm(text: str, llm: Optional[LLMClient]) -> tuple[str, str]:
    """Return (text, mode). Falls back to the template when no LLM or the fact check fails."""
    if llm is None or isinstance(llm, NoLLM):
        return text, "template"
    prompt = ("Rewrite this daily warehouse P&L alert for a busy operations manager in 2-3 short sentences. "
              "Keep every number exactly as written, do not add any new number or fact.\n\n" + text)
    answer = llm.generate(prompt)
    if answer and _numbers_supported(answer, text):
        return answer.strip(), f"llm:{llm.name}"
    return text, "template"


def _numbers_supported(answer: str, facts: str) -> bool:
    def numbers(s: str) -> set[str]:
        return set(re.findall(r"\d+(?:\.\d+)?", s.replace(",", "")))
    return numbers(answer).issubset(numbers(facts))


def severity_counts(days: list[DayResult]) -> dict[str, int]:
    counts = {s.value: 0 for s in Severity}
    for day in days:
        for anomaly in day.anomalies:
            counts[anomaly.severity.value] += 1
    return counts
