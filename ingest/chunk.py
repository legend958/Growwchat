"""Phase 2 — Ingestion: chunk the cleaned source documents.

Pipeline step: **Chunk**.

Strategy (approved per implementation.md Phase 2):

* **Unit of chunking:** one ``##`` section per chunk. The corpus is
  structured fact sheets, so each section (e.g. "Fees and charges",
  "Lock-in") is a self-contained semantic group that maps 1:1 to the
  FAQ questions.
* **Chunk size:** ``CHUNK_SIZE`` (default 700) acts as a safety cap;
  real sections are <= 400 chars, so nothing is fragmented today.
* **Overlap:** ``CHUNK_OVERLAP`` (default 100) applies only when a
  section must be split (future-proofing).
* **Empty sections are skipped** (e.g. the empty "Lock-in" heading on
  non-ELSS schemes) — no fabricated "not applicable" text.
* **Context prefix:** every chunk text starts with a self-describing
  "Scheme: ... | Category: ... | Section: ..." line so a chunk is
  grounded and readable even when retrieved in isolation.
* **Metadata:** ``chunk_id``, ``scheme``, ``category``, ``doc_type``,
  ``source_url``, ``source_title``, ``section``, ``position``,
  ``last_updated`` (ingestion date).

All chunks are written to ``artifacts/chunks.txt`` in a human-inspectable
format. Nothing is embedded here (that is Phase 3).

Usage
-----
    python -m ingest.chunk                      # uses config defaults
    python -m ingest.chunk --chunk-size 900 --overlap 150
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import config
from ingest.load import parse_sources, slugify


@dataclass
class Chunk:
    chunk_id: str
    scheme: str
    category: str
    doc_type: str
    source_url: str
    source_title: str
    section: str
    position: int
    last_updated: str
    text: str


# ---------------------------------------------------------------------------
# Document parsing
# ---------------------------------------------------------------------------
def parse_document(text: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Split a cleaned document into its header block and ``##`` sections.

    Returns ``(header, sections)`` where
    ``header`` has ``title``/``source_url``/``doc_type`` keys and
    ``sections`` is a list of ``(heading, body)`` tuples (body without the
    heading line, preserving relative line breaks).
    """
    header: dict[str, str] = {"title": "", "source_url": "", "doc_type": ""}
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        if current_heading is not None:
            sections.append((current_heading, "\n".join(current_lines)))
        current_heading = None
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip()
        elif current_heading is not None:
            current_lines.append(line)
        else:  # header block
            if line.startswith("# "):
                header["title"] = line[2:].strip()
            elif line.startswith("Source:"):
                header["source_url"] = line.split("Source:", 1)[1].strip()
            elif line.startswith("Document type:"):
                header["doc_type"] = line.split("Document type:", 1)[1].strip()

    flush()
    return header, sections


# ---------------------------------------------------------------------------
# Splitting oversized sections (fallback path)
# ---------------------------------------------------------------------------
def _split_oversized(body: str, max_size: int, overlap: int) -> list[str]:
    """Split an oversized section body on line boundaries with overlap."""
    if len(body) <= max_size:
        return [body]

    lines = body.splitlines()
    blocks: list[str] = []
    current: list[str] = []

    for line in lines:
        if current and len("\n".join(current + [line])) > max_size:
            block = "\n".join(current)
            blocks.append(block)
            tail = block[-overlap:] if overlap and len(block) > overlap else block
            current = [tail] if tail else []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


# ---------------------------------------------------------------------------
# Chunking a single document
# ---------------------------------------------------------------------------
def chunk_document(
    text: str,
    *,
    scheme: str,
    category: str,
    doc_type: str,
    source_url: str,
    source_title: str,
    chunk_size: int,
    overlap: int,
    last_updated: str,
) -> list[Chunk]:
    """Turn one cleaned document into a list of :class:`Chunk`."""
    header, sections = parse_document(text)
    slug = slugify(source_title or scheme)

    chunks: list[Chunk] = []
    position = 0

    for section_heading, body in sections:
        body = body.strip()
        if not body:  # skip empty sections (e.g. Lock-in on non-ELSS)
            continue

        pieces = _split_oversized(body, chunk_size, overlap)
        prefix = (
            f"Scheme: {scheme} | Category: {category or 'n/a'} | "
            f"Section: {section_heading}"
        )

        for piece in pieces:
            position += 1
            chunk_body = piece.strip()
            text_block = f"{prefix}\n\n## {section_heading}\n{chunk_body}"
            chunks.append(
                Chunk(
                    chunk_id=f"{slug}-{position:04d}",
                    scheme=scheme,
                    category=category,
                    doc_type=doc_type,
                    source_url=source_url,
                    source_title=source_title,
                    section=section_heading,
                    position=position,
                    last_updated=last_updated,
                    text=text_block,
                )
            )

    return chunks


# ---------------------------------------------------------------------------
# Orchestration + artifacts
# ---------------------------------------------------------------------------
def chunk_all(
    *,
    chunk_size: int = config.CHUNK_SIZE,
    overlap: int = config.CHUNK_OVERLAP,
    last_updated: str | None = None,
) -> list[Chunk]:
    """Chunk every cleaned document in ``data/raw``."""
    sources_by_url = {s.url: s for s in parse_sources()}
    today = last_updated or date.today().isoformat()

    all_chunks: list[Chunk] = []
    for raw_file in sorted(config.RAW_DIR.glob("*.txt")):
        text = raw_file.read_text(encoding="utf-8")
        header, _ = parse_document(text)

        source = sources_by_url.get(header["source_url"])
        scheme = source.scheme if source else header["title"]
        category = source.category if source else ""
        doc_type = source.doc_type if source else header.get("doc_type", "scheme page")
        source_title = header["title"] or scheme

        all_chunks.extend(
            chunk_document(
                text,
                scheme=scheme,
                category=category,
                doc_type=doc_type,
                source_url=header["source_url"],
                source_title=source_title,
                chunk_size=chunk_size,
                overlap=overlap,
                last_updated=today,
            )
        )
    return all_chunks


def write_chunks_file(chunks: list[Chunk], path: Path = config.ARTIFACTS_DIR / "chunks.txt") -> Path:
    """Write chunks in a human-inspectable format."""
    path.parent.mkdir(parents=True, exist_ok=True)

    rule = "=" * 80
    with path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(f"{rule}\nchunk: {chunk.chunk_id}\n")
            fh.write("metadata:\n")
            fh.write(f"  scheme: {chunk.scheme}\n")
            fh.write(f"  category: {chunk.category}\n")
            fh.write(f"  doc_type: {chunk.doc_type}\n")
            fh.write(f"  section: {chunk.section}\n")
            fh.write(f"  position: {chunk.position}\n")
            fh.write(f"  last_updated: {chunk.last_updated}\n")
            fh.write(f"  source_title: {chunk.source_title}\n")
            fh.write(f"  source_url: {chunk.source_url}\n")
            fh.write("text:\n")
            fh.write(chunk.text)
            fh.write("\n")
    return path


def _print_summary(chunks: list[Chunk]) -> None:
    per_source: dict[str, list[Chunk]] = {}
    for c in chunks:
        per_source.setdefault(c.scheme, []).append(c)

    print("\nChunking summary")
    print("-" * 70)
    for scheme, cs in per_source.items():
        avg = sum(len(c.text) for c in cs) / len(cs)
        print(f"  {scheme:<40} chunks={len(cs):>2}  avg_len={avg:6.1f}")
    print("-" * 70)
    print(f"Total chunks: {len(chunks)}")
    if chunks:
        avg_all = sum(len(c.text) for c in chunks) / len(chunks)
        longest = max(chunks, key=lambda c: len(c.text))
        print(
            f"Average chunk length: {avg_all:.1f} chars | "
            f"longest: {longest.chunk_id} ({len(longest.text)} chars)"
        )


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Phase 2: chunk cleaned MF documents.")
    parser.add_argument("--chunk-size", type=int, default=config.CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=config.CHUNK_OVERLAP)
    parser.add_argument("--last-updated", default=None, help="ISO date (default: today)")
    parser.add_argument(
        "--out",
        type=Path,
        default=config.ARTIFACTS_DIR / "chunks.txt",
        help="Output file for the inspectable chunk dump.",
    )
    args = parser.parse_args(argv)

    chunks = chunk_all(
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        last_updated=args.last_updated,
    )
    out = write_chunks_file(chunks, args.out)
    print(f"Wrote {len(chunks)} chunk(s) to {out}")
    _print_summary(chunks)

    over = [c for c in chunks if len(c.text) > args.chunk_size]
    if over:
        print(f"\nWARNING: {len(over)} chunk(s) exceed CHUNK_SIZE={args.chunk_size}")
        for c in over:
            print(f"  - {c.chunk_id} ({len(c.text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())