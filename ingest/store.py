"""Phase 3 — Vector store: persist chunks to ChromaDB on disk.

ChromaDB is persisted to ``config.VECTOR_DB_PATH`` so ingestion runs **once**
and is not repeated on every restart. Upserts are idempotent: re-running with
the same ``chunk_id`` ids replaces rather than duplicates entries.

The collection is created with cosine distance so scores can be interpreted
as ``1 - cosine_distance`` at retrieval.
"""

from __future__ import annotations

from typing import Any

import chromadb

import config
from ingest.chunk import Chunk


def get_client(path: str | None = None) -> chromadb.PersistentClient:
    """Open (or create) the persistent ChromaDB client on disk."""
    return chromadb.PersistentClient(path=str(path or config.VECTOR_DB_PATH))


def get_collection(
    client: chromadb.PersistentClient | None = None,
    name: str | None = None,
) -> chromadb.Collection:
    """Create-or-get the collection with cosine space."""
    client = client or get_client()
    return client.get_or_create_collection(
        name=name or config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def chunk_metadata(chunk: Chunk) -> dict[str, Any]:
    """Metadata stored alongside each chunk (see architecture.md §5.1)."""
    return {
        "chunk_id": chunk.chunk_id,
        "scheme": chunk.scheme,
        "category": chunk.category,
        "doc_type": chunk.doc_type,
        "section": chunk.section,
        "position": chunk.position,
        "last_updated": chunk.last_updated,
        "source_title": chunk.source_title,
        "source_url": chunk.source_url,
    }


def upsert_chunks(
    chunks: list[Chunk],
    embeddings: Any,
    collection: chromadb.Collection | None = None,
) -> int:
    """Idempotently upsert chunks + embeddings + metadata. Returns count stored."""
    if not chunks:
        return 0
    collection = collection or get_collection()
    vectors = embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings

    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=vectors,
        metadatas=[chunk_metadata(c) for c in chunks],
    )
    return len(chunks)


def collection_count(
    collection: chromadb.Collection | None = None,
) -> int:
    """Number of documents currently in the collection."""
    collection = collection or get_collection()
    return collection.count()


if __name__ == "__main__":
    print(f"Collection '{config.COLLECTION_NAME}' contains {collection_count()} item(s)")