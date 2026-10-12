"""Central configuration for the Mutual Fund FAQ RAG chatbot.

Values mirror ``architecture.md`` §10. HTTP settings are consumed by the
Phase 1 ingestion loader; the remaining keys are declared here so later
phases (chunking, embedding, retrieval, generation) share one source of
truth.

All values can be overridden with environment variables (see ``.env.example``).
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional at import time
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - graceful when dotenv is absent
    pass


# --- Paths ---------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_HTML_DIR = RAW_DIR / "html"
SOURCES_FILE = DATA_DIR / "sources.md"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
CHUNKS_FILE = ARTIFACTS_DIR / "chunks.txt"
CHUNKS_WITH_EMBEDDINGS_FILE = ARTIFACTS_DIR / "chunks_with_embeddings.txt"


# --- Embedding / Vector DB (Phase 3) -------------------------------------
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", str(ROOT_DIR / "chroma_db"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "mf_faq")


# --- Chunking (Phase 2) ---------------------------------------------------
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))


# --- Retrieval (Phase 4) --------------------------------------------------
TOP_K = int(os.getenv("TOP_K", "5"))
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.30"))


# --- Generation (Phase 5) -------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY") or ""
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))


# --- HTTP (Phase 1 ingestion loader) -------------------------------------
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "2"))
