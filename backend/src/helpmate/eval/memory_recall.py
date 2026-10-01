# Stand-in for Workstream A - not part of the Part C deliverable
"""Memory recall benchmark: does memory search find the right approved fact for a message?

The spec's target is recall@5 >= 0.8 on seeded data. The seeded memory is 20 made-up facts of the
kind a student would save; 21 messages should each find one of them, and 4 unrelated messages
should find nothing. It uses the same MemoryRetriever and embedding model as the app (Ollama,
on the CPU), and sweeps the score threshold to show why MIN_SCORE is where it is.

    cd backend
    uv run helpmate-memory-bench            # writes docs/benchmarks/memory-recall.md
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from helpmate.adapters.fakes.memory_repos import InMemoryMemoryRepo
from helpmate.adapters.ollama_llm import OllamaEmbeddings
from helpmate.domain.models import MemoryFact
from helpmate.memory.retrieval import MARGIN, MIN_SCORE, TOP_K, MemoryRetriever, ScoredFact
from helpmate.settings import REPO_ROOT, Settings

FACTS = {
    "advisor": "my advisor is Dr. Lee",
    "advisor-email": "my advisor's email is lee@mcmaster.ca",
    "peanuts": "I'm allergic to peanuts",
    "sister": "my sister Priya's birthday is March 3",
    "parking": "I park in lot M on campus",
    "student-no": "my student number is 400123456",
    "capstone": "my capstone group meets Tuesdays at 4pm",
    "gym": "my gym membership renews on the 1st of every month",
    "bus": "I take the 51 bus to campus",
    "mom-phone": "my mom's phone number is 905-555-0142",
    "study": "I prefer morning study sessions",
    "laptop": "my laptop is a Dell XPS 15",
    "landlord": "my landlord is Mr. Singh",
    "rent": "rent is due on the 1st",
    "coffee": "my favourite coffee is an oat latte",
    "job": "I work part-time at the library on weekends",
    "dentist": "my dentist is Dr. Wong at Main St Dental",
    "thesis": "my thesis is about local LLM assistants",
    "vegetarian": "I'm vegetarian",
    "friend": "my best friend is Sam",
}
QUERIES = {  # message -> the fact it needs (None: should find nothing)
    "who is my advisor?": "advisor",
    "what's my advisor's email address?": "advisor-email",
    "email my advisor about the deadline": "advisor-email",
    "can I eat a peanut butter cookie?": "peanuts",
    "when is my sister's birthday?": "sister",
    "where do I park at school?": "parking",
    "what's my student ID?": "student-no",
    "when does my capstone group meet?": "capstone",
    "when does my gym membership renew?": "gym",
    "which bus do I take to campus?": "bus",
    "what's my mom's number?": "mom-phone",
    "when do I like to study?": "study",
    "what laptop do I have?": "laptop",
    "who's my landlord?": "landlord",
    "when is my rent due?": "rent",
    "order my usual coffee": "coffee",
    "am I working this weekend?": "job",
    "book a dentist appointment": "dentist",
    "what is my thesis about?": "thesis",
    "suggest a dinner recipe for me": "vegetarian",
    "who is my best friend?": "friend",
    "what is 2 plus 2?": None,
    "tell me a joke": None,
    "what's the capital of Canada?": None,
    "how does photosynthesis work?": None,
}
THRESHOLDS = (0.45, 0.50, 0.55, 0.60, 0.65)


async def rankings(retriever: MemoryRetriever) -> dict[str, list[ScoredFact]]:
    return {q: await retriever.relevant(q) for q in QUERIES}


def report(ranked: dict[str, list[ScoredFact]], model: str, ms_per_query: float) -> str:
    relevant = {q: f for q, f in QUERIES.items() if f is not None}
    unrelated = [q for q, f in QUERIES.items() if f is None]

    def rank(q: str) -> int | None:
        ids = [s.fact.id for s in ranked[q]]
        return ids.index(relevant[q]) + 1 if relevant[q] in ids else None

    def recall_at(k: int) -> float:
        return sum(1 for q in relevant if (r := rank(q)) is not None and r <= k) / len(relevant)

    lines = [
        "# Memory recall benchmark",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M} · model `{model}` on the CPU "
        f"· {ms_per_query:.0f} ms per message (warm)",
        f"- Seeded memory: {len(FACTS)} facts · {len(relevant)} messages that need one, "
        f"{len(unrelated)} that need none",
        "",
        "| Recall@1 | Recall@3 | Recall@5 (spec ≥ 0.8) |",
        "|---|---|---|",
        f"| {recall_at(1):.2f} | {recall_at(3):.2f} | **{recall_at(5):.2f}** |",
        "",
        f"## What the agent gets: top {TOP_K}, score ≥ threshold, within {MARGIN} of the best",
        "",
        "Extra facts = facts given to a message that needed a different one (some are related,",
        "e.g. the advisor's email for 'who is my advisor?').",
        "",
        "| Threshold | Right fact included | Unrelated messages given a fact "
        "| Extra facts, no margin | Extra facts, with margin |",
        "|---|---|---|---|---|",
    ]

    def given(q: str, threshold: float, margin: float) -> list[str]:
        top = ranked[q][:TOP_K]
        floor = max(threshold, top[0].score - margin) if top else threshold
        return [s.fact.id for s in top if s.score >= floor]

    for threshold in THRESHOLDS:
        hit = sum(1 for q, f in relevant.items() if f in given(q, threshold, MARGIN))
        noise = sum(1 for q in unrelated if given(q, threshold, MARGIN))
        extra = {
            m: sum(len([i for i in given(q, threshold, m) if i != f]) for q, f in relevant.items())
            for m in (2.0, MARGIN)
        }
        mark = " (used)" if abs(threshold - MIN_SCORE) < 1e-9 else ""
        lines.append(
            f"| {threshold:.2f}{mark} | {hit}/{len(relevant)} | {noise}/{len(unrelated)} "
            f"| {extra[2.0]} | {extra[MARGIN]} |"
        )
    lines += [
        "",
        "## Per message (top 3 scores)",
        "",
        "| Message | Needs | Rank | Top 3 |",
        "|---|---|---|---|",
    ]
    for q, needed in QUERIES.items():
        top = ", ".join(f"{s.fact.id} {s.score:.2f}" for s in ranked[q][:3])
        r = rank(q) if needed else None
        shown = r if r else ("-" if needed is None else "miss")
        lines.append(f"| {q} | {needed or '-'} | {shown} | {top} |")
    return "\n".join(lines) + "\n"


async def run(model: str, url: str) -> str:
    memory = InMemoryMemoryRepo()
    for fact_id, text in FACTS.items():
        await memory.add_fact(
            MemoryFact(id=fact_id, text=text, source="seed", created_at=datetime.now(UTC))
        )
    async with httpx.AsyncClient(base_url=url, timeout=120) as client:
        embeddings = OllamaEmbeddings(client, model, on_cpu=True)
        # full rankings: every fact, no threshold (the report applies thresholds itself)
        retriever = MemoryRetriever(
            memory, embeddings, top_k=len(FACTS), min_score=-1.0, margin=2.0
        )
        await retriever.relevant("warm up")  # loads the model and embeds the facts
        started = time.perf_counter()
        ranked = await rankings(retriever)
        ms = (time.perf_counter() - started) * 1000 / len(QUERIES)
    return report(ranked, model, ms)


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=settings.ollama_embed_model)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "benchmarks")
    args = parser.parse_args()
    markdown = asyncio.run(run(args.model, settings.ollama_url))
    out = args.out / "memory-recall.md"
    out.write_text(markdown, encoding="utf-8", newline="\n")
    print(markdown.encode("ascii", "replace").decode())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
