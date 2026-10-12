"""Phase 8 — Guardrail regression tests (detector false-positive guards).

Plain-script test (no pytest dependency): exits non-zero if any case fails.

    python -m tests.test_guardrails

Covers:
* PII / opinion / performance questions that MUST be short-circuited (correct kind).
* Factual questions that MUST NOT be blocked (no false triggers) — including the
  "capital gains" tax/statement case that must not read as a performance request.
* ``postcheck`` invariants: exactly one citation, URLs stripped, <= 3 sentences,
  freshness footer.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from query.guardrails import (  # noqa: E402
    not_found_message,
    postcheck,
    precheck,
    refusal,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# --- Cases that must be refused, with the expected kind --------------------
MUST_CATCH: list[tuple[str, str]] = [
    # PII
    ("My PAN is ABCDE1234F, is ELSS good for me?", "pii"),
    ("My account number is 123456789012.", "pii"),
    ("Here is my OTP 123456, please verify.", "pii"),
    ("You can email me at investor@example.com about the fund.", "pii"),
    ("Call me on my phone 9876543210.", "pii"),
    # Opinion / advice
    ("Should I buy HDFC Small Cap Fund right now?", "opinion"),
    ("Is it a good time to invest in HDFC funds?", "opinion"),
    ("Which fund is better?", "opinion"),
    ("Can you recommend a fund for me?", "opinion"),
    ("I want to invest my money in HDFC.", "opinion"),
    ("Help me build my portfolio.", "opinion"),
    # Performance / returns
    ("What returns did HDFC Large Cap Fund give last year?", "performance"),
    ("What is the CAGR of the fund?", "performance"),
    ("How much profit will I make?", "performance"),
    ("What gains did it make over 3 years?", "performance"),
    ("What is its past performance?", "performance"),
]

# --- Factual questions that must NOT be blocked ----------------------------
MUST_NOT_CATCH: list[str] = [
    "What is the expense ratio of HDFC Small Cap Fund?",
    "What is the exit load of HDFC Balanced Advantage Fund?",
    "What is the minimum SIP amount for HDFC Large Cap Fund?",
    "How long is the lock-in period for HDFC ELSS Tax Saver Fund?",
    "What is the riskometer of HDFC ELSS Tax Saver Fund?",
    "What is the benchmark of HDFC Small Cap Fund?",
    "Who are the fund managers of HDFC Equity Fund?",
    "What is the NAV of HDFC Balanced Advantage Fund?",
    "What is the Direct Growth plan of HDFC Equity Fund?",  # "growth" must not trigger
    "How do I download my capital gains statement?",  # tax/statement, not performance
    "What is the capital gains tax on ELSS?",  # tax context
    "How many days does redemption take?",
    "Is HDFC Balanced Advantage Fund a hybrid fund?",
    "What is the minimum lumpsum investment?",
]


def main() -> int:
    failures: list[str] = []

    for question, expected_kind in MUST_CATCH:
        pre = precheck(question)
        if pre is None:
            failures.append(f"NOT CAUGHT ({expected_kind}): {question}")
        elif pre.kind != expected_kind:
            failures.append(f"WRONG KIND (want {expected_kind}, got {pre.kind}): {question}")

    for question in MUST_NOT_CATCH:
        pre = precheck(question)
        if pre is not None:
            failures.append(f"FALSE TRIGGER ({pre.kind}): {question}")

    # Refusals always carry an official http link; not-found never fabricates.
    for kind in ("pii", "opinion", "performance"):
        from query.guardrails import PrecheckResult

        text = refusal(PrecheckResult(kind=kind, reason="test"))
        if "http" not in text:
            failures.append(f"refusal({kind}) missing official link")
    if "couldn't find" not in not_found_message().lower():
        failures.append("not_found_message wording changed unexpectedly")

    # postcheck invariants.
    raw = "First fact. Second fact. Third fact. Fourth fact that must be cut. Source: http://evil.example"
    out = postcheck(raw, "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth", "2026-10-12")
    body = out.partition("\n\nSource: ")[0]
    if out.count("Source:") != 1:
        failures.append("postcheck: expected exactly one Source: line")
    if "evil.example" in out:
        failures.append("postcheck: invented URL was not stripped")
    if body.count(".") > 3:
        failures.append(f"postcheck: more than 3 sentences kept: {body!r}")
    if not out.rstrip().endswith("Last updated from sources: 2026-10-12"):
        failures.append("postcheck: freshness footer missing")

    total = len(MUST_CATCH) + len(MUST_NOT_CATCH) + 3 + 4
    print(f"guardrail cases: {len(MUST_CATCH)} must-catch, {len(MUST_NOT_CATCH)} must-not-catch, "
          f"+ refusal/postcheck invariants")
    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print(f"\nALL {total} GUARDRAIL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())