"""Phase 6 — Guarded query pipeline: precheck -> retrieve -> generate -> postcheck.

Chains the Phase 4/5 pipeline inside the Phase 6 guardrails:

1. **Pre-check** (``query.guardrails.precheck``): PII, opinion/advice, and
   return/performance questions short-circuit *before* retrieval/LLM.
2. **Retrieve** (Phase 4) + **Generate** (Phase 5) for factual questions.
3. **Post-check** (``query.guardrails.postcheck``): strip invented URLs/citations,
   cap at ≤3 sentences, attach exactly one ``Source: <url>`` line and the
   ``Last updated from sources:`` footer.
4. Not-found and refusal cases produce clean, facts-only messages that never
   fabricate and never echo PII.

Usage
-----
    python -m query.pipeline "What is the exit load of HDFC Small Cap Fund?"
    python -m query.pipeline "Should I buy HDFC funds now?"
    python -m query.pipeline "My PAN is ABCDE1234F — is ELSS good?"
"""

from __future__ import annotations

import argparse
import sys

import config
from query.generate import Answer, generate
from query.guardrails import not_found_message, postcheck, precheck, refusal
from query.retrieve import search

NOT_FOUND = Answer(
    found=False,
    answer=None,
    source_url="",
    source_title="",
    last_updated="",
)


def ask(
    question: str,
    *,
    top_k: int = config.TOP_K,
    threshold: float = config.SCORE_THRESHOLD,
) -> Answer:
    """Answer ``question`` with the full guarded pipeline."""
    # 1. Pre-check (short-circuit PII / advice / performance).
    pre = precheck(question)
    if pre is not None:
        return Answer(
            found=False,
            answer=None,
            source_url="",
            source_title="",
            last_updated="",
            refusal=refusal(pre),
        )

    # 2. Retrieve.
    result = search(question, top_k=top_k, threshold=threshold)
    if result.empty:
        return NOT_FOUND

    # 3. Generate.
    draft = generate(question, result)
    if not draft.found:
        return NOT_FOUND

    # 4. Post-check: single citation + ≤3 sentences + freshness footer.
    guarded = postcheck(draft.answer, draft.source_url, draft.last_updated)
    return Answer(
        found=True,
        answer=guarded,
        source_url=draft.source_url,
        source_title=draft.source_title,
        last_updated=draft.last_updated,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Phase 6: guarded facts-only Q&A against the official FAQ corpus."
    )
    parser.add_argument("question", help="The user's question.")
    parser.add_argument("--top-k", type=int, default=config.TOP_K)
    parser.add_argument("--threshold", type=float, default=config.SCORE_THRESHOLD)
    args = parser.parse_args(argv)

    answer = ask(args.question, top_k=args.top_k, threshold=args.threshold)
    print(f"Q: {args.question}\n")
    if answer.refusal:
        print(answer.refusal)
    elif answer.found:
        print(answer.answer)
    else:
        print(not_found_message())
    return 0


if __name__ == "__main__":
    sys.exit(main())