"""
Tiny retrieval component for the knowledge base (the "R" in RAG).

A dependency-free TF-IDF ranker over the sections of `knowledge_base.md`.
For a few dozen short passages this is accurate, instant and easy to
explain. Swapping in embeddings (sentence-transformers + FAISS) later would
only change this file.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_BASE = Path(__file__).with_name("knowledge_base.md")
TITLE_WEIGHT = 4

_STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "in", "and", "or", "for", "on", "by", "what", "which",
    "how", "why", "does", "do", "it", "this", "that", "be", "with", "as", "at", "from", "can", "i", "me",
    "my", "we", "our", "you", "your", "there", "their", "was", "were", "has", "have", "if", "so", "per",
}


@dataclass(frozen=True)
class Passage:
    title: str
    text: str


@dataclass(frozen=True)
class ScoredPassage:
    passage: Passage
    score: float


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1]


class KnowledgeBaseRetriever:
    def __init__(self, path: Path = KNOWLEDGE_BASE):
        self.passages = self._load(path)
        # Titles are repeated so a question naming the topic ("ESIC wage ceiling") ranks that section first.
        self._doc_tokens = [Counter(tokenize(" ".join([p.title] * TITLE_WEIGHT) + " " + p.text)) for p in self.passages]
        document_frequency = Counter(token for tokens in self._doc_tokens for token in tokens)
        total = len(self.passages)
        self._idf = {t: math.log((1 + total) / (1 + df)) + 1 for t, df in document_frequency.items()}

    def search(self, question: str, top_k: int = 3, min_score: float = 0.12) -> list[ScoredPassage]:
        query = Counter(tokenize(question))
        if not query:
            return []
        scored = [ScoredPassage(p, self._cosine(query, tokens)) for p, tokens in zip(self.passages, self._doc_tokens)]
        scored = self._prefer_named_scheme(query, scored)
        scored = [s for s in scored if s.score >= min_score]
        return sorted(scored, key=lambda s: s.score, reverse=True)[:top_k]

    @staticmethod
    def _prefer_named_scheme(query: Counter, scored: list[ScoredPassage]) -> list[ScoredPassage]:
        """A question about ESIC only should not be answered with a PF passage (and vice versa)."""
        asks_pf, asks_esic = "pf" in query or "epf" in query, "esic" in query or "esi" in query
        if asks_pf == asks_esic:
            return scored
        excluded = "ESIC" if asks_pf else "PF"
        return [s for s in scored if not s.passage.title.upper().startswith(excluded + " ")]

    def _cosine(self, query: Counter, document: Counter) -> float:
        def weight(counter: Counter) -> dict[str, float]:
            return {t: c * self._idf.get(t, 0.0) for t, c in counter.items()}

        q, d = weight(query), weight(document)
        dot = sum(q[t] * d.get(t, 0.0) for t in q)
        norm = math.sqrt(sum(v * v for v in q.values())) * math.sqrt(sum(v * v for v in d.values()))
        return dot / norm if norm else 0.0

    @staticmethod
    def _load(path: Path) -> list[Passage]:
        passages: list[Passage] = []
        for block in path.read_text(encoding="utf-8").split("\n## ")[1:]:
            title, _, body = block.partition("\n")
            passages.append(Passage(title.strip(), " ".join(body.split())))
        return passages
