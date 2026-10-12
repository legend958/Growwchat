"""Phase 3 — End-to-end ingestion entrypoint.

Runs the full pipeline once:

    Load -> Chunk -> Embed -> Store (ChromaDB, persisted)

Re-running is idempotent: the load stage overwrites the cleaned documents,
the chunk stage is deterministic (same chunk ids), and the store stage
upserts, so the collection count stays stable.

Usage
-----
    python -m ingest.run                 # full pipeline (re-fetches pages)
    python -m ingest.run --no-fetch      # reuse data/raw/*.txt if present
"""

from __future__ import annotations

import argparse
import sys
import time

import config


def _print_stage(stage: str, message: str) -> None:
    print(f"\n[{stage}] {message}")


def run_pipeline(
    *,
    fetch: bool = True,
    chunk_size: int = config.CHUNK_SIZE,
    overlap: int = config.CHUNK_OVERLAP,
    embed_batch_size: int = 32,
) -> int:
    t0 = time.time()

    # ---- Load -----------------------------------------------------------
    if fetch:
        _print_stage("Load", "fetching and cleaning official source pages")
        from ingest.load import load_all

        results = load_all()
        ok = [r for r in results if r.error is None and r.clean_chars > 0]
        print(f"  loaded {len(ok)}/{len(results)} documents")
        if len(ok) != len(results):
            print("  WARNING: some sources failed; see load summary above.")
    else:
        _print_stage("Load", "skipped (reusing data/raw/*.txt)")

    # ---- Chunk ----------------------------------------------------------
    _print_stage("Chunk", f"chunking (size={chunk_size}, overlap={overlap})")
    from ingest.chunk import chunk_all, write_chunks_file

    chunks = chunk_all(chunk_size=chunk_size, overlap=overlap)
    write_chunks_file(chunks)
    print(f"  produced {len(chunks)} chunks  ->  artifacts/chunks.txt")

    # ---- Embed ----------------------------------------------------------
    _print_stage("Embed", f"embedding with {config.EMBEDDING_MODEL}")
    from ingest.embed import embed_texts, load_embedder

    embedder = load_embedder()
    vectors = embed_texts(
        [c.text for c in chunks], batch_size=embed_batch_size, embedder=embedder
    )
    print(f"  embedded {vectors.shape[0]} vectors, dim={vectors.shape[1]}")

    # ---- Store ----------------------------------------------------------
    _print_stage("Store", f"upserting into ChromaDB '{config.COLLECTION_NAME}'")
    from ingest.store import collection_count, get_collection, upsert_chunks

    collection = get_collection()
    stored = upsert_chunks(chunks, vectors, collection=collection)
    total = collection_count(collection)
    print(f"  upserted {stored}/{len(chunks)}; collection count = {total}")

    if total != len(chunks):
        print(f"  WARNING: collection count {total} != chunk count {len(chunks)}")

    print(f"\nDone in {time.time() - t0:.1f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Phase 3: run the full ingestion pipeline (load -> chunk -> embed -> store)."
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip re-fetching sources; reuse data/raw/*.txt.",
    )
    parser.add_argument("--chunk-size", type=int, default=config.CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=config.CHUNK_OVERLAP)
    parser.add_argument("--embed-batch-size", type=int, default=32)
    args = parser.parse_args(argv)

    return run_pipeline(
        fetch=not args.no_fetch,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        embed_batch_size=args.embed_batch_size,
    )


if __name__ == "__main__":
    sys.exit(main())