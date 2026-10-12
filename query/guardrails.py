"""Phase 6 — Guardrails: Citation, Refusal, PII, Length, Freshness.

Implements the architecture.md §7 guardrail table:

* **Pre-check** (``precheck``): detect opinionated/portfolio intent, return /
  performance requests, and PII in the question. PII is never echoed, stored,
  or sent to the LLM. Return/performance requests are short-circuited with a
  link to the official scheme page (no computed returns).
* **Refusal / not-found formatting** (``refusal``, ``not_found_message``):
  polite facts-only responses; every refusal carries a link to an official
  AMC/AMFI/SEBI educational page or the official scheme page.
* **Post-check** (``postcheck``): strip stray URLs/"Source:" lines a model may
  emit, cap the answer at 3 sentences, then attach exactly one
  ``Source: <url>`` citation line plus the ``Last updated from sources:``
  freshness footer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from ingest.load import parse_sources

# ---------------------------------------------------------------------------
# Official educational links (AMC / AMFI / SEBI only)
# ---------------------------------------------------------------------------
EDUCATIONAL_LINKS: list[dict[str, str]] = [
    {
        "name": "AMFI — Know Your Mutual Fund (investor education)",
        "url": "https://www.amfiindia.com/investor-corner/know-your-mutual-fund.html",
    },
    {
        "name": "AMFI — Investor Corner",
        "url": "https://www.amfiindia.com/investor-corner.html",
    },
    {
        "name": "SEBI — Investor Protection",
        "url": "https://www.sebi.gov.in/investor-protection.html",
    },
]
DEFAULT_EDU_LINK = EDUCATIONAL_LINKS[0]["url"]

# ---------------------------------------------------------------------------
# Detection patterns (case-insensitive unless stated)
# ---------------------------------------------------------------------------

# PII *data* patterns
PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_RE = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")  # 12 digits, optional sep
AADHAAR_FLAT_RE = re.compile(r"\b\d{12}\b")
ACCOUNT_RE = re.compile(r"\b\d{9,18}\b")  # account / folio-like numbers
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?:\+91[ -]?)?[6-9]\d{9}\b")  # Indian mobile

# PII *phrase* triggers ("my pan", "otp", "share my", ...)
PII_PHRASES = [
    r"\botp\b",
    r"\bone[- ]time password\b",
    r"\bmy (pan|pan card|aadhaar|aadhar|aadhaar card|account|account number|folio)\b",
    r"\bshare my\b",
    r"\bmy phone\b",
    r"\bmy email\b",
    r"\bmy mobile\b",
]
PII_PHRASE_RE = re.compile("|".join(PII_PHRASES), re.IGNORECASE)

# Opinionated / portfolio-intent phrases — multi-word so factual uses of
# words like "buy" or "portfolio" don't get blocked.
OPINION_PATTERNS = [
    r"\bshould i (buy|sell|invest|withdraw|switch|exit)\b",
    r"\bis it (a )?good (time|idea) to (buy|invest|sell|withdraw)\b",
    r"\bgood time to invest\b",
    r"\brecommend\b",
    r"\bsuggest me\b",
    r"\bwhat do you (recommend|suggest)\b",
    r"\bbest (mutual )?fund\b",
    r"\btop (performing )?fund\b",
    r"\bwhich (mutual )?fund\b",
    r"\bwhich is (the )?better\b",
    r"\bcompare\b",
    r"\bi want to invest\b",
    r"\binvest my money\b",
    r"\bworth investing\b",
    r"\bbuild my portfolio\b",
    r"\bmy portfolio\b",
    r"\bsip for (me|my)\b",
    r"\bhow much (should|can) i\b",
    r"\badvice\b",
    r"\badvise\b",
    r"\binvest in hdfc\b",
]
OPINION_RE = re.compile("|".join(OPINION_PATTERNS), re.IGNORECASE)

# Return / performance requests. Deliberately excludes bare "growth" (the
# "Direct Growth" plan name appears inside scheme names and questions).
PERFORMANCE_PATTERNS = [
    r"\breturns?\b",
    r"\breturned\b",
    r"\bperformance\b",
    r"\bperformed\b",
    r"\byield\b",
    r"\bcagr\b",
    r"\bcompound\w*\b",
    r"\bprofit\w*\b",
    r"\bappreciat\w*\b",
    # Bare "gains" also matches tax/statement phrasing (e.g. "capital gains
    # statement"), which is not a performance request, so exclude that context.
    r"(?<!capital )\bgains?\b",
    r"\bgave me\b",
    r"\bhow much did it (earn|give|make)\b",
    r"\bexpected return\b",
    r"\bwill it give\b",
    r"\bwhat will (my|the) return\b",
]
PERFORMANCE_RE = re.compile("|".join(PERFORMANCE_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pre-check
# ---------------------------------------------------------------------------
@dataclass
class PrecheckResult:
    """Why a question was short-circuited before retrieval/generation."""

    kind: str  # "pii" | "opinion" | "performance"
    reason: str
    scheme_url: str = ""


@lru_cache(maxsize=1)
def _schemes():
    """Cached list of official sources (guarding against import-time I/O)."""
    try:
        return parse_sources()
    except Exception:  # pragma: no cover - never break the pipeline on this
        return []


def _base_scheme_name(name: str) -> str:
    """Strip the plan suffix: 'HDFC Large Cap Fund – Direct Growth' -> base name."""
    return re.split(r"\s+[–—-]\s+", name, maxsplit=1)[0].strip()


def _scheme_url_for(question: str) -> str:
    """Return the official scheme URL when the question names a scheme."""
    lowered = question.lower().strip()
    for source in _schemes():
        base = _base_scheme_name(source.scheme).lower()
        if base and base in lowered:
            return source.url
    return ""


def _pii_match(question: str) -> re.Match | None:
    patterns = (PAN_RE, AADHAAR_RE, AADHAAR_FLAT_RE, ACCOUNT_RE, EMAIL_RE, PHONE_RE)
    for pattern in patterns:
        match = pattern.search(question)
        if match:
            return match
    return None


def precheck(question: str) -> PrecheckResult | None:
    """Return a :class:`PrecheckResult` when the question must be refused.

    Priority: PII > opinion/advice > performance. PII wins so personal data is
    never passed downstream (and never echoed in a refusal).
    """
    question = (question or "").strip()

    # 1. PII — never accept, never echo.
    if _pii_match(question) or PII_PHRASE_RE.search(question):
        return PrecheckResult(
            kind="pii",
            reason="Personal identifiers detected in the question.",
        )

    # 2. Opinion / portfolio intent.
    if OPINION_RE.search(question):
        return PrecheckResult(
            kind="opinion",
            reason="Advisory / opinionated intent detected.",
            scheme_url=_scheme_url_for(question),
        )

    # 3. Return / performance requests.
    if PERFORMANCE_RE.search(question):
        return PrecheckResult(
            kind="performance",
            reason="Return / performance request detected.",
            scheme_url=_scheme_url_for(question),
        )

    return None


# ---------------------------------------------------------------------------
# Refusal & not-found formatting
# ---------------------------------------------------------------------------
def refusal(pre: PrecheckResult) -> str:
    """Polite facts-only refusal with an official link, tailored to the kind."""
    if pre.kind == "pii":
        return (
            "Please don't share personal details (PAN, Aadhaar, account "
            "numbers, OTPs, emails, or phone numbers) with me — they are "
            "neither needed nor accepted here. I only answer factual "
            "questions from the official HDFC scheme documents. For general "
            f"investor education, see: {DEFAULT_EDU_LINK}"
        )

    if pre.kind == "performance":
        target = pre.scheme_url or DEFAULT_EDU_LINK
        return (
            "I'm a facts-only assistant and can't provide performance or "
            "return figures, and I don't compute or compare returns. Please "
            f"refer to the official scheme and factsheet page: {target}"
        )

    # opinion
    target = pre.scheme_url or DEFAULT_EDU_LINK
    return (
        "I'm a facts-only assistant for HDFC Mutual Fund FAQs and can't offer "
        "investment advice, opinions, or recommendations about buying, "
        "selling, or timing the market. For general investor education, see: "
        f"{target}"
    )


def not_found_message(question: str = "") -> str:
    """Message when retrieval finds nothing above threshold (no fabrication)."""
    return (
        "I couldn't find that in the official sources. I answer only from the "
        "official HDFC scheme pages — e.g. expense ratio, exit load, minimum "
        "investment, lock-in, riskometer, benchmark, NAV, or fund managers."
    )


# ---------------------------------------------------------------------------
# Post-check: citation, length, freshness
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*https?://[^)\s]+\s*\)")
_CITATION_LABEL_RE = re.compile(
    r"(?i)\b(?:source[s]?|reference[s]?|citation[s]?)\b\s*:"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _strip_urls_and_citations(text: str) -> str:
    """Remove URLs, markdown links, and stray citation labels anywhere.

    Note: ``Source:`` labels are matched globally (not just at line starts) so
    a model that writes one mid-sentence cannot slip a second citation past the
    post-check. The URL that follows such a label is removed by the URL regex.
    """
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("", text)
    text = _CITATION_LABEL_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(" \n-")


def _truncate_to_sentences(text: str, n: int = 3) -> str:
    """Collapse whitespace and keep at most ``n`` sentences."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(flat) if s.strip()]
    clipped = " ".join(sentences[:n])
    if clipped and not clipped.endswith((".", "!", "?")):
        clipped += "."
    return clipped


def postcheck(
    raw_text: str,
    source_url: str,
    last_updated: str,
    *,
    max_sentences: int = 3,
) -> str:
    """Produce the final guarded answer string.

    Exactly one ``Source: <url>`` line appears; the freshness footer is
    appended; the answer body is capped at ``max_sentences`` sentences and is
    stripped of any URLs or citation lines the model may have invented.
    """
    body = _truncate_to_sentences(_strip_urls_and_citations(raw_text or ""), max_sentences)
    if not body:
        body = "I couldn't find a complete answer in the official sources."

    lines = [body, "", f"Source: {source_url}"]
    if last_updated:
        lines.append(f"Last updated from sources: {last_updated}")
    return "\n".join(lines)