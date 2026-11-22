"""
"Ask" assistant: answers questions about one verification job and PF/ESIC rules.

Flow (Retrieval-Augmented Generation with guardrails):
    1. Classify the question: employee lookup | status list | summary | rules | off-topic
    2. Retrieve facts:
         - job questions  -> structured queries on the stored results (never free-form SQL/NoSQL)
         - rules questions -> top passages from the knowledge base (TF-IDF retriever)
    3. Build a template answer from those facts (always available, no AI needed)
    4. If an LLM is configured, ask it to phrase the answer using ONLY the facts
    5. Fact-check: every number in the LLM answer must exist in the facts,
       otherwise the template answer is returned instead.

Verdicts themselves are never produced or changed by the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.shared.llm import LLMClient, NoLLM
from app.case_study_2.assistant.retriever import KnowledgeBaseRetriever
from app.case_study_2.models import Status
from app.case_study_2.repository import JobRepository, JobStatus, ResultRepository

MAX_LISTED = 15

REFUSAL = ("I can answer questions about this verification job (for example \"Who is missing in ESIC?\", "
           "\"Why is Vikram flagged?\", \"Give me a summary\") or about PF/ESIC rules "
           "(\"What is the ESIC wage ceiling?\"). Please rephrase your question.")

_STATUS_KEYWORDS = [
    (("name mismatch", "wrong name", "different name", "name differ"), Status.NAME_MISMATCH),
    (("amount mismatch", "short", "less deposit", "amount differ", "underpaid", "under paid"), Status.AMOUNT_MISMATCH),
    (("missing", "not found", "not deposited", "absent"), Status.MISSING),
    (("matched", "correct", "fine", "ok "), Status.MATCHED),
]
_ACTION_WORDS = ("follow up", "follow-up", "followup", "action", "problem", "issue", "flagged", "need attention")
_REVIEW_WORDS = ("review", "probable", "check manually")
_SUMMARY_WORDS = ("summary", "overview", "how many", "count", "total", "overall", "match rate", "statistics")
_COMMON_WORDS = {"WHY", "WHAT", "WHO", "THE", "AND", "FOR", "ARE", "WAS", "HAS", "ESIC", "UAN", "ECR", "SHOW",
                 "LIST", "GIVE", "TELL", "ABOUT", "EMPLOYEE", "EMPLOYEES", "STATUS", "NAME", "AMOUNT", "MISSING",
                 "MATCHED", "MISMATCH", "FLAGGED", "WHICH", "HOW", "MANY", "NOT", "WITH", "FROM", "THIS", "THAT"}


@dataclass
class AssistantAnswer:
    answer: str
    intent: str
    mode: str                      # "template" or "llm:<provider>"
    sources: list[str] = field(default_factory=list)


@dataclass
class _Context:
    intent: str
    facts: list[str]
    template_answer: str
    sources: list[str] = field(default_factory=list)


class ComplianceAssistant:
    def __init__(self, jobs: JobRepository, results: ResultRepository,
                 retriever: Optional[KnowledgeBaseRetriever] = None, llm: Optional[LLMClient] = None):
        self.jobs = jobs
        self.results = results
        self.retriever = retriever or KnowledgeBaseRetriever()
        self.llm = llm or NoLLM()

    def ask(self, job_id: str, question: str) -> AssistantAnswer:
        question = (question or "").strip()
        if len(re.findall(r"[A-Za-z]{2,}", question)) < 2:
            return AssistantAnswer(REFUSAL, "invalid", "template")

        job = self.jobs.get(job_id)
        if not job or job["status"] != JobStatus.COMPLETED.value:
            return AssistantAnswer("Results for this job are not ready yet.", "not_ready", "template")

        context = self._build_context(question, job, self.results.all_employees(job_id))
        if context.intent == "off_topic":
            return AssistantAnswer(REFUSAL, "off_topic", "template")

        llm_text = self._ask_llm(question, context)
        if llm_text:
            return AssistantAnswer(llm_text, context.intent, f"llm:{self.llm.name}", context.sources)
        return AssistantAnswer(context.template_answer, context.intent, "template", context.sources)

    # ------------------------------------------------------------------ #
    # Retrieval
    # ------------------------------------------------------------------ #

    def _build_context(self, question: str, job: dict, employees: list[dict]) -> _Context:
        lowered = f" {question.lower()} "
        checks = _checks_mentioned(lowered)

        people = _find_employees(question, employees)
        if people:
            lines = [_describe_employee(e) for e in people[:5]]
            return _Context("employee_lookup", lines, "\n\n".join(lines), ["verification results"])

        status = next((s for words, s in _STATUS_KEYWORDS if any(w in lowered for w in words)), None)
        if status or any(w in lowered for w in _ACTION_WORDS + _REVIEW_WORDS):
            return self._status_context(lowered, status, checks, employees)

        if any(w in lowered for w in _SUMMARY_WORDS):
            lines = _summary_lines(job)
            return _Context("summary", lines, "\n".join(lines), ["job summary"])

        passages = self.retriever.search(question)
        if passages:
            facts = [f"{p.passage.title}: {p.passage.text}" for p in passages]
            # Show the runner-up only when it is nearly as relevant as the best passage.
            shown = [p for p in passages[:2] if p.score >= 0.8 * passages[0].score]
            answer = "\n\n".join(f"**{p.passage.title}** - {p.passage.text}" for p in shown)
            return _Context("rules", facts, answer, [f"knowledge base: {p.passage.title}" for p in passages])

        return _Context("off_topic", [], "")

    def _status_context(self, lowered: str, status: Optional[Status], checks: list[str],
                        employees: list[dict]) -> _Context:
        lines: list[str] = []
        for check in checks:
            label = check.upper()
            if status:
                selected = [e for e in employees if e[check]["status"] == status.value]
                title = f"{len(selected)} employee(s) have {label} status '{status.value}'"
            elif any(w in lowered for w in _REVIEW_WORDS):
                selected = [e for e in employees if e[check]["needs_review"]]
                title = f"{len(selected)} employee(s) are {label} matched but need review"
            else:
                selected = [e for e in employees if e[check]["status"] != Status.MATCHED.value]
                title = f"{len(selected)} employee(s) need follow-up for {label}"
            lines.append(title + (":" if selected else "."))
            for emp in selected[:MAX_LISTED]:
                lines.append(f"- {emp['name']} (row {emp['row_number']}): {emp[check]['status']} - "
                             f"{emp[check]['reason']}")
            if len(selected) > MAX_LISTED:
                lines.append(f"- ... and {len(selected) - MAX_LISTED} more (see the Excel report).")
        return _Context("status_list", lines, "\n".join(lines), ["verification results"])

    # ------------------------------------------------------------------ #
    # Generation (optional) + fact check
    # ------------------------------------------------------------------ #

    def _ask_llm(self, question: str, context: _Context) -> Optional[str]:
        if isinstance(self.llm, NoLLM):
            return None
        facts = "\n".join(context.facts)
        prompt = (
            "You are a compliance assistant for PF/ESIC verification of contract workers.\n"
            "Answer the question using ONLY the facts below. If the facts do not contain the answer, say so.\n"
            "Do not invent names, numbers or rules. Keep it short and use plain language.\n\n"
            f"FACTS:\n{facts}\n\nQUESTION: {question}\nANSWER:"
        )
        text = self.llm.generate(prompt)
        if text and _numbers_supported(text, facts + " " + question):
            return text
        return None


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _checks_mentioned(lowered: str) -> list[str]:
    checks = [c for c in ("pf", "esic") if re.search(rf"\b{c}\b", lowered)]
    if "esi " in lowered and "esic" not in checks:
        checks.append("esic")
    return checks or ["pf", "esic"]


def _find_employees(question: str, employees: list[dict]) -> list[dict]:
    """Match by identifier digits first, then by name words present in the question."""
    numbers = set(re.findall(r"\d{10,12}", question))
    if numbers:
        by_id = [e for e in employees if e.get("uan") in numbers or e.get("ip_number") in numbers]
        if by_id:
            return by_id

    words = {w for w in re.findall(r"[A-Za-z]{3,}", question.upper()) if w not in _COMMON_WORDS}
    if not words:
        return []
    scored = []
    for emp in employees:
        name_words = set(emp["name"].upper().split())
        score = len(words & name_words)
        if score:
            scored.append((score, emp))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [emp for score, emp in scored if score == best]


def _describe_employee(emp: dict) -> str:
    return (f"{emp['name']} (wagesheet row {emp['row_number']}, UAN {emp.get('uan') or 'n/a'}, "
            f"IP {emp.get('ip_number') or 'n/a'})\n"
            f"PF: {emp['pf']['status']} - {emp['pf']['reason']}\n"
            f"ESIC: {emp['esic']['status']} - {emp['esic']['reason']}")


def _summary_lines(job: dict) -> list[str]:
    summary = job.get("summary") or {}
    lines = [f"Employees in wagesheet: {summary.get('total_employees', 0)}"]
    for check in ("pf", "esic"):
        data = summary.get(check, {})
        counts = ", ".join(f"{k}: {v}" for k, v in data.get("counts", {}).items())
        lines.append(f"{check.upper()} - {counts}. Match rate {data.get('match_rate', 0)}%. "
                     f"Short-deposited amount Rs {data.get('short_deposit_amount', 0):,.0f}. "
                     f"Needs review: {data.get('needs_review', 0)}.")
    return lines


def _numbers_supported(answer: str, facts: str) -> bool:
    """Every number the LLM states must appear in the facts (ignores list numbering like '1.')."""
    answer = re.sub(r"(?m)^\s*\d+[.)]\s", "", answer)
    known = set(re.findall(r"\d+(?:\.\d+)?", facts.replace(",", "")))
    stated = set(re.findall(r"\d+(?:\.\d+)?", answer.replace(",", "")))
    return stated.issubset(known)
