"""Ingestion package: load → chunk → embed → store.

Phase 1 implements :mod:`ingest.load` (fetch + normalize the official
source pages). Later phases add chunking, embedding, and vector-store
persistence.
"""
