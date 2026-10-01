# Stand-in for Workstream A - not part of the Part C deliverable
"""Semantic search over the owner's approved memory facts, on this machine.

Facts are embedded once (and again only when edited) with the local embedding model, kept in an
in-process index, and compared with each message by cosine similarity. A single owner has tens to
hundreds of facts, so a scan is ~1 ms; Workstream B can move the vectors into pgvector
(`memory_facts.embedding`) without changing this interface.

Measured Sep 30/Oct 1 with nomic-embed-text on the CPU (llama stays 100% on the GPU): ~30 ms per
query; relevant facts score 0.63-0.81, unrelated ones ~0.41-0.44, hence MIN_SCORE. Retrieval is
best-effort: if embedding fails, the agent answers without memory instead of failing.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from helpmate.domain.models import MemoryFact
from helpmate.domain.ports import EmbeddingPort, MemoryRepo

log = logging.getLogger("helpmate.memory")

TOP_K = 3
MIN_SCORE = 0.55  # tuned for nomic-embed-text; see the recall benchmark (eval/memory_recall.py)
# ...and only facts close to the best match: with the floor alone, "who is my advisor?" also got
# "my landlord is Mr. Singh" (0.57 vs 0.81), which then showed up in the "From memory" note.
MARGIN = 0.08
# nomic-embed-text was trained with task prefixes; other models get the plain text
_PREFIXES = {"nomic": ("search_query: ", "search_document: ")}


@dataclass(frozen=True)
class ScoredFact:
    fact: MemoryFact
    score: float


class MemoryRetriever:
    def __init__(
        self,
        memory: MemoryRepo,
        embeddings: EmbeddingPort,
        top_k: int = TOP_K,
        min_score: float = MIN_SCORE,
        margin: float = MARGIN,
    ) -> None:
        self._memory = memory
        self._embeddings = embeddings
        self._top_k = top_k
        self._min_score = min_score
        self._margin = margin
        self._index: dict[str, tuple[str, list[float]]] = {}  # fact id -> (text, vector)
        prefix = next((p for key, p in _PREFIXES.items() if key in embeddings.name), ("", ""))
        self._query_prefix, self._document_prefix = prefix

    async def relevant(self, text: str) -> list[ScoredFact]:
        """The facts that matter for `text`, best first: at most top_k, each >= min_score and
        within `margin` of the best one."""
        try:
            facts = await self._memory.find_facts()
            if not facts:
                return []
            await self._refresh(facts)
            [query] = await self._embeddings.embed([self._query_prefix + text])
        except Exception:
            log.warning("memory search failed; answering without memory", exc_info=True)
            return []
        scored = sorted(
            (ScoredFact(f, _cosine(query, self._index[f.id][1])) for f in facts),
            key=lambda s: s.score,
            reverse=True,
        )
        floor = max(self._min_score, scored[0].score - self._margin)
        return [s for s in scored[: self._top_k] if s.score >= floor]

    async def _refresh(self, facts: list[MemoryFact]) -> None:
        """Embed new or edited facts (one batch); forget deleted ones."""
        current = {f.id for f in facts}
        for gone in self._index.keys() - current:
            del self._index[gone]
        stale = [f for f in facts if self._index.get(f.id, ("",))[0] != f.text]
        if stale:
            vectors = await self._embeddings.embed([self._document_prefix + f.text for f in stale])
            for fact, vector in zip(stale, vectors, strict=True):
                self._index[fact.id] = (fact.text, vector)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
