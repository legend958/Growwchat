"""Phase 5 — Generation: grounded prompt builder + LLM call (Groq).

Query-side step **Generate**.

* Retrieved chunks (Phase 4) are turned into a prompt that grounds the model
  strictly in the provided excerpts.
* The prompt forbids investment advice, return comparisons, and performance
  claims; requires at most 3 sentences; and requires a single
  ``Source: <url>`` citation line.
* The LLM is called over **Groq's OpenAI-compatible REST API** via ``requests``
  (already a project dependency — no extra SDK needed).
* The API key is read from ``GROQ_API_KEY`` (or ``LLM_API_KEY``) via ``.env``.
* An empty (or unanswerable) retrieval produces a **not-found signal** —
  never a hallucinated answer. Phase 6 formats the public-facing refusal.

Usage
-----
    python -m query.generate "Expense ratio of HDFC Large Cap Fund?"
    python -m query.generate "Is it a good time to invest?" --top-k 5
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import requests

import config
from query.retrieve import RetrievalResult

SYSTEM_PROMPT = """You are a facts-only assistant for HDFC Mutual Fund FAQs.

You answer questions using ONLY the official scheme-page excerpts provided in
the user message as "Context". Follow these rules strictly:

1. FACTS ONLY. State only facts that appear in the context. Never give
   investment advice, opinions, buy/sell guidance, or recommendations.
   Never make performance or return claims, and never compare funds'
   performance or returns.
2. If the context cannot answer the question, reply exactly with:
   NOT_FOUND_IN_SOURCES
   and nothing else. Never guess, infer, or invent facts.
3. Answer in at most 3 sentences.
4. Do not include any URLs, links, or "Source:" lines in your answer. The
   citation is attached separately."""

NOT_FOUND_MARKER = "NOT_FOUND_IN_SOURCES"


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM is not configured (e.g. missing API key)."""


class LLMCallError(RuntimeError):
    """Raised when the upstream LLM call fails."""


@dataclass
class Answer:
    """Structured generation result.

    ``found`` is False for the not-found signal and refusals (``answer`` is
    then None). ``refusal`` carries the ready-to-display facts-only refusal
    text when the pre-check short-circuits the question (Phase 6); the
    user-facing not-found text is formatted by guardrails.not_found_message.
    """

    found: bool
    answer: str | None
    source_url: str
    source_title: str
    last_updated: str
    refusal: str | None = None


NOT_FOUND = Answer(
    found=False,
    answer=None,
    source_url="",
    source_title="",
    last_updated="",
)


def build_prompt(query: str, result: RetrievalResult) -> tuple[str, str]:
    """Build (system, user) message pair from the retrieved chunks."""
    context_blocks: list[str] = []
    seen: set[str] = set()
    for i, chunk in enumerate(result.chunks, start=1):
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        context_blocks.append(f"[{i}] (source: {chunk.source_url})\n{chunk.text}")

    user_prompt = (
        "Context (official HDFC scheme pages):\n\n"
        + "\n\n".join(context_blocks)
        + f"\n\nQuestion: {query}\n\n"
        + "Answer in at most 3 sentences, with no URLs or Source lines:"
    )
    return SYSTEM_PROMPT, user_prompt


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call Groq's OpenAI-compatible chat completions endpoint."""
    if not config.LLM_API_KEY:
        raise LLMConfigurationError(
            "GROQ_API_KEY is not set. Add it to .env "
            "(see .env.example) or export it in the environment."
        )

    url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=config.REQUEST_TIMEOUT
        )
    except requests.RequestException as exc:
        raise LLMCallError(f"LLM request failed: {exc}") from exc

    if response.status_code != 200:
        raise LLMCallError(
            f"LLM API error {response.status_code}: {response.text[:400]}"
        )

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMCallError(f"Unexpected LLM API response: {data}") from exc
    return content


def generate(query: str, result: RetrievalResult) -> Answer:
    """Generate a grounded answer from retrieval results.

    Returns the not-found signal when retrieval is empty *or* when the model
    reports it cannot answer from the context (no fabrication either way).
    """
    if result.empty:
        return NOT_FOUND

    system_prompt, user_prompt = build_prompt(query, result)
    content = call_llm(system_prompt, user_prompt)

    if NOT_FOUND_MARKER in content.upper():
        return NOT_FOUND

    top = result.chunks[0]
    return Answer(
        found=True,
        answer=content,
        source_url=top.source_url,
        source_title=top.source_title,
        last_updated=top.last_updated,
    )


def format_answer(answer: Answer) -> str:
    """Format a found answer with its single citation and freshness footer.

    Exactly one ``Source: <url>`` line appears (citation), followed by the
    ``Last updated from sources: <date>`` freshness footer required by the PRD.
    """
    if not answer.found:
        return "[not found in sources]"
    return (
        f"{answer.answer}\n\n"
        f"Source: {answer.source_url}\n"
        f"Last updated from sources: {answer.last_updated}"
    )


def _print_answer(answer: Answer) -> None:
    print(format_answer(answer))


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Phase 5: retrieve + generate a grounded answer via Groq."
    )
    parser.add_argument("query", help="The user's question.")
    parser.add_argument("--top-k", type=int, default=config.TOP_K)
    parser.add_argument("--threshold", type=float, default=config.SCORE_THRESHOLD)
    args = parser.parse_args(argv)

    from query.retrieve import search

    result = search(args.query, top_k=args.top_k, threshold=args.threshold)
    answer = generate(args.query, result)
    _print_answer(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())