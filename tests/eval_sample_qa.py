"""Phase 8 — Evaluation harness: sample Q&A accuracy + retrieval sanity.

Runs the real guarded pipeline (ChromaDB + MiniLM + Groq) over a fixed case set:

* **factual** — answer is found, cites the expected scheme, contains the key
  fact, has exactly one citation + the freshness footer, is <= 3 sentences,
  and the retrieval top-1 chunk comes from the expected scheme.
* **opinion / PII** — refused (no citation, no PII echo).
* **performance** — refused with a link to an official page (factsheet/scheme).
* **out-of-scope / not-covered** — not found (no grounded answer, no refusal).

Writes ``artifacts/phase8_eval.json`` and exits non-zero if any case fails.

Usage
-----
    python -m tests.eval_sample_qa
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from ingest.embed import load_embedder  # noqa: E402
from ingest.store import get_collection  # noqa: E402
from query.pipeline import ask  # noqa: E402
from query.retrieve import search  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# --- Case set ------------------------------------------------------------
# `scheme` is the Groww slug the answer must cite; `expect` is a list of
# case-insensitive substrings that must appear in the answer body.
FACTUAL: list[dict] = [
    {"label": "expense ratio (Small Cap)", "q": "What is the expense ratio of HDFC Small Cap Fund?",
     "scheme": "hdfc-small-cap-fund-direct-growth", "expect": ["0.79"]},
    {"label": "expense ratio (Large Cap)", "q": "What is the expense ratio of HDFC Large Cap Fund?",
     "scheme": "hdfc-large-cap-fund-direct-growth", "expect": ["1.04"]},
    {"label": "exit load (Balanced Advantage)", "q": "What is the exit load of HDFC Balanced Advantage Fund?",
     "scheme": "hdfc-balanced-advantage-fund-direct-growth", "expect": ["1%"]},
    {"label": "exit load (ELSS)", "q": "What is the exit load of HDFC ELSS Tax Saver Fund?",
     "scheme": "hdfc-elss-tax-saver-fund-direct-plan-growth", "expect": ["nil"]},
    {"label": "minimum SIP (Large Cap)", "q": "What is the minimum SIP amount for HDFC Large Cap Fund?",
     "scheme": "hdfc-large-cap-fund-direct-growth", "expect": ["100"]},
    {"label": "ELSS lock-in", "q": "How long is the lock-in period for HDFC ELSS Tax Saver Fund?",
     "scheme": "hdfc-elss-tax-saver-fund-direct-plan-growth", "expect": ["3 year"]},
    {"label": "riskometer (ELSS)", "q": "What is the riskometer of HDFC ELSS Tax Saver Fund?",
     "scheme": "hdfc-elss-tax-saver-fund-direct-plan-growth", "expect": ["very high"]},
    {"label": "benchmark (Small Cap)", "q": "What is the benchmark of HDFC Small Cap Fund?",
     "scheme": "hdfc-small-cap-fund-direct-growth", "expect": ["bse 250 smallcap"]},
    {"label": "fund managers (Equity/Flexi Cap)", "q": "Who are the fund managers of HDFC Equity Fund?",
     "scheme": "hdfc-equity-fund-direct-growth", "expect": ["dhruv muchhal", "amit ganatra"]},
    {"label": "NAV (Balanced Advantage)", "q": "What is the NAV of HDFC Balanced Advantage Fund?",
     "scheme": "hdfc-balanced-advantage-fund-direct-growth", "expect": ["546"]},
]

NEGATIVE: list[dict] = [
    {"label": "opinion -> refusal", "kind": "opinion",
     "q": "Should I invest in HDFC Small Cap Fund right now?"},
    {"label": "performance -> refusal + official link", "kind": "performance",
     "q": "What returns did HDFC Large Cap Fund give last year?"},
    {"label": "PII -> refusal", "kind": "pii",
     "q": "My PAN is ABCDE1234F, is the ELSS fund good for me?"},
    {"label": "out-of-scope -> not found", "kind": "not_found",
     "q": "What is the USD to INR exchange rate today?"},
    {"label": "statement download (not in corpus) -> not found", "kind": "not_found",
     "q": "How do I download my capital gains statement?"},
]


def _body(answer_text: str) -> str:
    return answer_text.partition("\n\nSource: ")[0]


def _sentence_count(text: str) -> int:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return len([p for p in parts if p.strip()])


def _check_factual(case: dict, collection, embedder) -> dict:
    result = {"label": case["label"], "question": case["q"], "checks": {}}
    res = search(case["q"], top_k=1, embedder=embedder, collection=collection)
    top = res.chunks[0] if res.chunks else None
    result["retrieval"] = {
        "matched": bool(top) and top.source_url.endswith("/" + case["scheme"]),
        "top_scheme": top.source_url.rsplit("/", 1)[-1] if top else None,
        "top_section": top.section if top else None,
        "score": round(top.score, 3) if top else None,
    }

    ans = ask(case["q"])
    body = _body(ans.answer) if ans.answer else ""
    result["answer"] = ans.answer
    result["source_url"] = ans.source_url
    result["checks"] = {
        "found": bool(ans.found),
        "right_scheme": ans.source_url.endswith("/" + case["scheme"]),
        "key_fact": all(e.lower() in body.lower() for e in case["expect"]),
        "one_citation": (ans.answer or "").count("Source:") == 1,
        "footer": "Last updated from sources:" in (ans.answer or ""),
        "<=3_sentences": _sentence_count(body) <= 3,
    }
    result["passed"] = bool(ans.found) and all(result["checks"].values()) and result["retrieval"]["matched"]
    return result


def _check_negative(case: dict) -> dict:
    ans = ask(case["q"])
    result = {
        "label": case["label"],
        "question": case["q"],
        "kind": case["kind"],
        "refusal": ans.refusal,
        "answer": ans.answer,
    }
    if case["kind"] in ("opinion", "pii"):
        result["passed"] = bool(ans.refusal) and not ans.found
    elif case["kind"] == "performance":
        result["passed"] = bool(ans.refusal) and "http" in (ans.refusal or "")
    else:  # not_found
        result["passed"] = (not ans.found) and (not ans.refusal)
    return result


def main() -> int:
    embedder = load_embedder()
    collection = get_collection()

    results = {"factual": [], "negative": []}
    print("=" * 78)
    print("PHASE 8 EVALUATION — sample Q&A accuracy + retrieval sanity")
    print("=" * 78)

    print("\n--- FACTUAL ---")
    for case in FACTUAL:
        r = _check_factual(case, collection, embedder)
        results["factual"].append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['label']}")
        print(f"       Q: {r['question']}")
        print(f"       A: {(r['answer'] or '').splitlines()[0]}")
        print(f"       src: {r['source_url']}")
        print(f"       retrieval: scheme={r['retrieval']['top_scheme']} "
              f"section={r['retrieval']['top_section']} score={r['retrieval']['score']} "
              f"match={r['retrieval']['matched']}")
        if not r["passed"]:
            print(f"       FAILED CHECKS: {r['checks']}")

    print("\n--- NEGATIVE / GUARDRAIL ---")
    for case in NEGATIVE:
        r = _check_negative(case)
        results["negative"].append(r)
        status = "PASS" if r["passed"] else "FAIL"
        shown = (r["refusal"] or "NOT FOUND (no grounded answer)").splitlines()
        print(f"[{status}] {r['label']}")
        print(f"       Q: {r['question']}")
        print(f"       -> {shown[0] if shown else ''}")
        if len(shown) > 1:
            print(f"          {shown[1]}")

    passed = sum(r["passed"] for r in results["factual"]) + sum(
        r["passed"] for r in results["negative"]
    )
    total = len(results["factual"]) + len(results["negative"])
    results["summary"] = {"passed": passed, "total": total}

    out = config.ARTIFACTS_DIR / "phase8_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"SUMMARY: {passed}/{total} cases passed  ->  {out}")
    print("=" * 78)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())