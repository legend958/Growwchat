"""Phase 4 — Retrieval: embed the question and search the vector store.

Pipeline step: **Retrieve** (query side).

* The question is embedded with the **same** model used at ingestion
  (``ingest.embed.load_embedder`` — one source of truth, never forked).
* ChromaDB returns top-``TOP_K`` matches by cosine distance.
* Distances are converted to similarity via ``score = 1 - distance`` and
  filtered by ``SCORE_THRESHOLD``; everything below the threshold is dropped.
* Results are structured :class:`RetrievedChunk` objects carrying the text
  plus the metadata needed for citations (``source_url``, ``source_title``,
  ``scheme``, …).

Empty results are represented explicitly (the empty case feeds the Phase 6
refusal / not-found fallback).

Usage
-----
    python -m query.retrieve "Expense ratio of HDFC Large Cap Fund?"
    python -m query.retrieve "ELSS lock-in period" --top-k 3 --threshold 0.3
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import config
from ingest.embed import load_embedder
from ingest.store import get_collection


@dataclass
class RetrievedChunk:
    """One retrieved chunk with its citation metadata and similarity score."""

    chunk_id: str
    text: str
    source_url: str
    source_title: str
    scheme: str
    category: str
    doc_type: str
    section: str
    last_updated: str
    score: float


@dataclass
class RetrievalResult:
    """Ranked, threshold-filtered results for a query."""

    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.chunks


def search(
    query: str,
    *,
    top_k: int = config.TOP_K,
    threshold: float = config.SCORE_THRESHOLD,
    embedder=None,
    collection=None,
) -> RetrievalResult:
    """Retrieve the top chunks for ``query``, filtered by similarity score."""
    embedder = embedder or load_embedder()
    collection = collection or get_collection()

    query_vector = embedder.encode([query])
    if query_vector.shape[0] > 1 or query_vector.shape[1] != config.EMBEDDING_DIM:
        raise ValueError(
            f"Expected a single {config.EMBEDDING_DIM}-dim query vector, "
            f"got shape {query_vector.shape}."
        )

    response = collection.query(
        query_embeddings=query_vector,
        n_results=max(1, int(top_k)),
        include=["documents", "metadatas", "distances"],
    )

    ids = (response.get("ids") or [[]])[0]
    documents = (response.get("documents") or [[]])[0]
    metadatas = (response.get("metadatas") or [[]])[0]
    distances = (response.get("distances") or [[]])[0]

    chunks: list[RetrievedChunk] = []
    for chunk_id, document, metadata, distance in zip(
        ids, documents, metadatas, distances
    ):
        score = 1.0 - float(distance)  # cosine distance -> cosine similarity
        if score < threshold:
            continue
        metadata = metadata or {}
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                text=document or "",
                source_url=metadata.get("source_url", ""),
                source_title=metadata.get("source_title", ""),
                scheme=metadata.get("scheme", ""),
                category=metadata.get("category", ""),
                doc_type=metadata.get("doc_type", ""),
                section=metadata.get("section", ""),
                last_updated=metadata.get("last_updated", ""),
                score=round(score, 4),
            )
        )

    return RetrievalResult(query=query, chunks=chunks)


def _print_result(result: RetrievalResult, top_k: int, threshold: float) -> None:
    print(f"\nQuery: {result.query}")
    if result.empty:
        print(f"  (no chunks above threshold {threshold})")
        return
    for i, c in enumerate(result.chunks, start=1):
        head = c.text.splitlines()[0] if c.text else "(empty)"
        print(f"  {i}. score={c.score:.4f}  chunk_id={c.chunk_id}")
        print(f"     section={c.section} | scheme={c.scheme}")
        print(f"     {head[:90]}")
        print(f"     source_url={c.source_url}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Phase 4: retrieve relevant chunks for a question."
    )
    parser.add_argument("query", help="The user's question.")
    parser.add_argument("--top-k", type=int, default=config.TOP_K)
    parser.add_argument("--threshold", type=float, default=config.SCORE_THRESHOLD)
    args = parser.parse_args(argv)

    result = search(args.query, top_k=args.top_k, threshold=args.threshold)
    _print_result(result, args.top_k, args.threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main())