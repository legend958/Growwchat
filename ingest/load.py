"""Phase 1 — Ingestion: load and normalize the official source pages.

Pipeline step: **Load**.

Reads the scoped URLs from ``data/sources.md``, fetches each page with a
browser-like User-Agent (with retries and timeouts), and writes:

* one cleaned, human-readable text file per source -> ``data/raw/<slug>.txt``
* an optional raw HTML cache                       -> ``data/raw/html/<slug>.html``
* a summary table printed to stdout

Content extraction
------------------
Groww scheme pages are Next.js apps: the factual scheme data is embedded as
JSON in the ``<script id="__NEXT_DATA__">`` payload rather than being present
as server-rendered prose. We therefore build the cleaned document from
``props.pageProps.mfServerSideData``, keeping **facts only** (identity, fees,
minimums, lock-in, risk grade, benchmark, fund details, official links) and
deliberately **excluding performance/return figures**. If that payload is
absent, we fall back to denoised visible HTML text.

Public sources only. This module never handles PII and never derives
performance/return figures.

Usage
-----
    python -m ingest.load                # fetch, clean, write (HTML cache on)
    python -m ingest.load --no-html-cache
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

import config


# Elements that never contain the scheme facts we want to keep (fallback path).
_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "form",
    "iframe",
    "button",
    "aside",
)

# Facts-only keywords used to sanity-check that a cleaned file is useful.
_FACT_KEYWORDS = (
    "expense ratio",
    "exit load",
    "sip",
    "lock-in",
    "lock in",
    "riskometer",
    "benchmark",
    "nav",
)


@dataclass
class Source:
    """A single scoped public source page."""

    index: int
    scheme: str
    category: str
    doc_type: str
    url: str

    @property
    def slug(self) -> str:
        """Filesystem-safe slug derived from the scheme name."""
        return slugify(self.scheme)


@dataclass
class LoadResult:
    """Outcome of loading one source."""

    source: Source
    status: int
    html_bytes: int
    clean_chars: int
    output_path: Path | None
    extraction: str = ""  # "json" or "html"
    keywords_found: list[str] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# sources.md parsing
# ---------------------------------------------------------------------------
def _is_separator_row(cells: Iterable[str]) -> bool:
    return all(set(cell) <= set("-: ") for cell in cells)


def _first_url(cells: Iterable[str]) -> str | None:
    for cell in cells:
        if cell.startswith("http://") or cell.startswith("https://"):
            return cell.strip()
    return None


def parse_sources(sources_file: Path = config.SOURCES_FILE) -> list[Source]:
    """Parse the markdown table in ``data/sources.md`` into :class:`Source`s.

    Columns are matched case-insensitively by header name (``scheme``,
    ``category``, ``doc type``, ``url``).
    """
    if not sources_file.exists():
        raise FileNotFoundError(f"Sources file not found: {sources_file}")

    text = sources_file.read_text(encoding="utf-8")
    header: list[str] | None = None
    sources: list[Source] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or _is_separator_row(cells):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue

        row = dict(zip(header, cells))
        url = _first_url(cells)
        if not url:
            continue
        digit = re.sub(r"\D", "", row.get("#", ""))
        sources.append(
            Source(
                index=int(digit) if digit else len(sources) + 1,
                scheme=row.get("scheme", f"source-{len(sources) + 1}"),
                category=row.get("category", ""),
                doc_type=row.get("doc type", row.get("doc_type", "")),
                url=url,
            )
        )

    if not sources:
        raise ValueError(
            f"No sources parsed from {sources_file}. Expected a markdown table "
            "with a 'URL' column."
        )
    return sources


def slugify(value: str) -> str:
    """Lowercase, normalize dashes, and replace non-alphanumerics with '-'."""
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    return value.strip("-").lower()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_html(url: str, session: requests.Session | None = None) -> str:
    """GET ``url`` with retries/backoff and return the decoded response body."""
    session = session or requests.Session()
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    last_error: Exception | None = None
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            response = session.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            # Guard against ISO-8859-1 defaulting when the server omits a charset.
            if not response.encoding or response.encoding.lower() in {
                "iso-8859-1",
                "latin-1",
            }:
                response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.RequestException as exc:  # network / HTTP error
            last_error = exc
            if attempt < config.REQUEST_RETRIES:
                time.sleep(config.RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(
        f"Failed to fetch {url} after {config.REQUEST_RETRIES} attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# Content extraction — structured facts from the embedded Next.js payload
# ---------------------------------------------------------------------------
def extract_next_data(html: str) -> dict[str, Any] | None:
    """Return ``props.pageProps`` from the ``__NEXT_DATA__`` script, if present."""
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("script", id="__NEXT_DATA__")
    if not node or not node.string:
        return None
    try:
        data = json.loads(node.string)
    except json.JSONDecodeError:
        return None
    return (data.get("props") or {}).get("pageProps")


def _fmt_percent(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return f"{value}%"


def _fmt_money(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_crore(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return f"Rs {float(value):,.2f} Cr"
    except (TypeError, ValueError):
        return str(value)


def _yes_no(value: Any) -> str | None:
    if value is None:
        return None
    return "Yes" if value else "No"


def _lock_in_text(mf: dict[str, Any]) -> str | None:
    lock = mf.get("lock_in") or {}
    years, months, days = lock.get("years"), lock.get("months"), lock.get("days")
    parts = []
    if years:
        parts.append(f"{years} year(s)")
    if months:
        parts.append(f"{months} month(s)")
    if days:
        parts.append(f"{days} day(s)")
    if parts:
        return " ".join(parts)

    extra_years = (mf.get("additional_details") or {}).get("lock_in_yrs")
    if extra_years:
        return f"{extra_years} year(s)"
    return None


def _risk_grade(mf: dict[str, Any]) -> str | None:
    stats = mf.get("return_stats") or []
    if isinstance(stats, list) and stats and isinstance(stats[0], dict):
        grade = stats[0].get("risk")
        if grade:
            return str(grade)
    nfo = mf.get("nfo_risk")
    return str(nfo) if nfo else None


def _fund_manager_names(mf: dict[str, Any]) -> str | None:
    details = mf.get("fund_manager_details") or []
    names: list[str] = []
    for item in details if isinstance(details, list) else []:
        if isinstance(item, dict):
            for key in ("name", "fund_manager_name", "person_name"):
                if item.get(key):
                    names.append(str(item[key]))
                    break
    if names:
        return ", ".join(dict.fromkeys(names))
    return mf.get("fund_manager")


def build_facts_text(mf: dict[str, Any], source: Source) -> str:
    """Render a facts-only, readable document from the scheme payload."""
    lines: list[str] = []
    add = lines.append

    def section(title: str) -> None:
        add("")
        add(f"## {title}")

    def kv(label: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        add(f"- {label}: {value}")

    category_info = mf.get("category_info") or {}
    amc_info = mf.get("amc_info") or {}

    add(f"# {mf.get('scheme_name') or source.scheme}")
    add(f"Source: {source.url}")
    add(f"Document type: {source.doc_type or 'scheme page'}")

    section("Scheme identity")
    kv("Scheme name", mf.get("scheme_name") or source.scheme)
    kv("Fund house", mf.get("fund_house") or amc_info.get("name"))
    kv("AMC", mf.get("amc"))
    kv("Super category", mf.get("super_category"))
    kv("Category", mf.get("category"))
    kv("Sub-category", mf.get("sub_category"))
    kv("Plan", mf.get("plan_type"))
    kv("Scheme type", mf.get("scheme_type"))
    kv("ISIN", mf.get("isin"))
    kv("Scheme code", mf.get("scheme_code"))

    section("Fees and charges")
    kv("Expense ratio", _fmt_percent(mf.get("expense_ratio")))
    kv("Base expense ratio", _fmt_percent(mf.get("base_expense_ratio")))
    kv("Exit load", mf.get("exit_load"))
    kv("Stamp duty", mf.get("stamp_duty"))
    kv("Portfolio turnover", _fmt_percent(mf.get("portfolio_turnover")))

    section("Minimum investments")
    kv("Minimum investment (lumpsum)", _fmt_money(mf.get("min_investment_amount")))
    kv("Minimum additional investment", _fmt_money(mf.get("mini_additional_investment")))
    kv("Minimum SIP amount", _fmt_money(mf.get("min_sip_investment")))
    kv("SIP multiplier", _fmt_money(mf.get("sip_multiplier")))
    kv("Minimum withdrawal", _fmt_money(mf.get("min_withdrawal")))
    kv("Purchase multiplier", _fmt_money(mf.get("purchase_multiplier")))
    kv("SIP allowed", _yes_no(mf.get("sip_allowed")))
    kv("Lumpsum allowed", _yes_no(mf.get("lumpsum_allowed")))

    section("Lock-in")
    kv("Lock-in period", _lock_in_text(mf))

    section("Risk and benchmark")
    kv("Riskometer (risk grade)", _risk_grade(mf))
    kv("NFO risk", mf.get("nfo_risk"))
    kv("Benchmark", mf.get("benchmark"))
    kv("Benchmark (full name)", mf.get("benchmark_name"))

    section("Fund details")
    kv("Fund manager", _fund_manager_names(mf))
    kv("Launch date", mf.get("launch_date"))
    kv("Allotment date", mf.get("allotment_date"))
    kv("Registrar and transfer agent", mf.get("registrar_agent"))
    kv("NAV", _fmt_money(mf.get("nav")) + f" (as of {mf['nav_date']})" if mf.get("nav") and mf.get("nav_date") else _fmt_money(mf.get("nav")))
    kv("AUM", _fmt_crore(mf.get("aum")))

    section("Description")
    if mf.get("description"):
        add(str(mf["description"]).strip())
    if category_info.get("category_helper_text"):
        add(f"Category note: {category_info['category_helper_text']}")
    if category_info.get("description"):
        add(f"Category description: {category_info['description']}")

    section("Tax impact")
    if category_info.get("tax_impact"):
        add(str(category_info["tax_impact"]).strip())

    section("Fund house (AMC)")
    kv("AMC name", amc_info.get("name"))
    kv("Website", amc_info.get("vro_website"))
    kv("Email", amc_info.get("email"))
    kv("Phone", amc_info.get("phone"))

    section("Official links")
    kv("Scheme page (source)", source.url)
    kv("AMC page", mf.get("amc_page_url"))
    kv("SID / scheme info", mf.get("sid_url"))

    # Collapse any accidental duplicate consecutive lines and trailing blanks.
    deduped: list[str] = []
    for line in lines:
        if deduped and line and deduped[-1] == line:
            continue
        deduped.append(line)

    return "\n".join(deduped).strip() + "\n"


# ---------------------------------------------------------------------------
# Content extraction — visible-HTML fallback
# ---------------------------------------------------------------------------
def clean_html(html: str) -> str:
    """Extract normalized text from visible HTML (fallback when no JSON payload)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    container = soup.find("main") or soup.body or soup
    raw_text = container.get_text(separator="\n")

    lines: list[str] = []
    for line in raw_text.splitlines():
        cleaned = re.sub(r"[ \t\u00a0]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)

    deduped: list[str] = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)
    return "\n".join(deduped)


def extract_document(html: str, source: Source) -> tuple[str, str]:
    """Return ``(text, extraction_kind)`` for a fetched page.

    Prefers the structured ``__NEXT_DATA__`` facts; falls back to visible HTML.
    """
    page_props = extract_next_data(html)
    if page_props:
        mf = page_props.get("mfServerSideData")
        if isinstance(mf, dict) and mf:
            return build_facts_text(mf, source), "json"
    return clean_html(html), "html"


def _keywords_found(text: str) -> list[str]:
    lowered = text.lower()
    return [kw for kw in _FACT_KEYWORDS if kw in lowered]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def load_all(
    sources: list[Source] | None = None,
    *,
    write_html_cache: bool = True,
) -> list[LoadResult]:
    """Fetch, extract, and persist every source. Returns one result per source."""
    sources = sources or parse_sources()

    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if write_html_cache:
        config.RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    results: list[LoadResult] = []

    for source in sources:
        try:
            html = fetch_html(source.url, session=session)
            html_bytes = len(html.encode("utf-8"))

            if write_html_cache:
                (config.RAW_HTML_DIR / f"{source.slug}.html").write_text(
                    html, encoding="utf-8"
                )

            text, kind = extract_document(html, source)
            out_path = config.RAW_DIR / f"{source.slug}.txt"
            out_path.write_text(text, encoding="utf-8")

            results.append(
                LoadResult(
                    source=source,
                    status=200,
                    html_bytes=html_bytes,
                    clean_chars=len(text),
                    output_path=out_path,
                    extraction=kind,
                    keywords_found=_keywords_found(text),
                )
            )
        except Exception as exc:  # noqa: BLE001 - report per-source failures
            results.append(
                LoadResult(
                    source=source,
                    status=0,
                    html_bytes=0,
                    clean_chars=0,
                    output_path=None,
                    error=str(exc),
                )
            )

    return results


def _print_summary(results: list[LoadResult]) -> None:
    print("\nIngestion (Load) summary")
    print("-" * 108)
    header = (
        f"{'#':<2} {'scheme':<38} {'kind':<5} {'status':<7} "
        f"{'bytes':>9} {'chars':>9}  output / error"
    )
    print(header)
    print("-" * 108)
    for r in results:
        scheme = (r.source.scheme[:36] + "..") if len(r.source.scheme) > 38 else r.source.scheme
        tail = (
            str(r.output_path.relative_to(config.ROOT_DIR))
            if r.output_path
            else f"ERROR: {r.error}"
        )
        print(
            f"{r.source.index:<2} {scheme:<38} {r.extraction or '-':<5} {r.status:<7} "
            f"{r.html_bytes:>9} {r.clean_chars:>9}  {tail}"
        )
    print("-" * 108)

    ok = [r for r in results if r.error is None and r.clean_chars > 0]
    print(f"Files written: {len(ok)}/{len(results)}")

    print("\nKeyword coverage (case-insensitive):")
    for r in results:
        if r.error:
            continue
        found = ", ".join(r.keywords_found) if r.keywords_found else "(none)"
        print(f"  - {r.source.slug}: {found}")


def main(argv: list[str] | None = None) -> int:
    try:  # keep en-dashes readable in the console
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Phase 1: load & normalize MF source pages."
    )
    parser.add_argument(
        "--no-html-cache",
        action="store_true",
        help="Skip writing raw HTML to data/raw/html/.",
    )
    args = parser.parse_args(argv)

    sources = parse_sources()
    print(f"Parsed {len(sources)} source(s) from {config.SOURCES_FILE.name}:")
    for s in sources:
        print(f"  {s.index}. [{s.category}] {s.scheme}\n     {s.url}")

    results = load_all(sources, write_html_cache=not args.no_html_cache)
    _print_summary(results)

    failures = [r for r in results if r.error is not None]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
