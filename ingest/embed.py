"""Phase 3 — Embedding: encode chunks with ``all-MiniLM-L6-v2`` (384-dim).

Model
-----
Uses the HF model ``sentence-transformers/all-MiniLM-L6-v2``.

Implementation note
-------------------
The plan calls for the ``sentence-transformers`` library, but this machine
runs Windows **Smart App Control in enforced mode**, which blocks
scikit-learn's compiled DLLs (``scikit-learn`` is imported unconditionally by
``sentence-transformers`` on startup). ``transformers`` + ``torch`` import
cleanly, so we load the *same model* directly and replicate the standard
MiniLM inference: mean pooling over token embeddings (attention-mask aware)
followed by L2 normalization -> the same 384-dim vectors. Because retrieval
uses cosine similarity (Chroma ``cosine`` space), any consistent
normalization choice preserves ranking.

The same embedder is used for chunks (ingestion) and questions (Phase 4), so
vectors are comparable. Runs locally with **no API key**.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

import config

_MODEL_CACHE: dict[str, "MiniLMEmbedder"] = {}


class MiniLMEmbedder:
    """Minimal sklearn-free wrapper around ``all-MiniLM-L6-v2``."""

    MAX_LENGTH = 512

    def __init__(self, model_name: str):
        import torch
        # Explicit model classes (transformers 4.x) — the 5.x auto/generation
        # path imports scikit-learn, which Smart App Control blocks on this
        # machine. These proven imports stay sklearn-free.
        from transformers.models.bert.modeling_bert import BertModel
        from transformers.models.bert.tokenization_bert_fast import BertTokenizerFast

        self.model_name = model_name
        self.tokenizer = BertTokenizerFast.from_pretrained(model_name)
        self.model = BertModel.from_pretrained(model_name)
        self.model.eval()
        self._torch = torch

    def encode(self, texts: Iterable[str], batch_size: int = 32) -> np.ndarray:
        """Encode a list of texts -> float32 array of shape (n, EMBEDDING_DIM)."""
        torch = self._torch
        items = list(texts)
        if not items:
            return np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32)

        pooled: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(items), batch_size):
                batch = items[start : start + batch_size]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.MAX_LENGTH,
                    return_tensors="pt",
                )
                outputs = self.model(**encoded)
                token_emb = outputs.last_hidden_state  # (B, L, D)
                mask = encoded["attention_mask"].unsqueeze(-1).float()
                summed = (token_emb * mask).sum(dim=1)
                counts = mask.sum(dim=1).clamp(min=1e-9)
                mean = summed / counts
                mean = torch.nn.functional.normalize(mean, p=2, dim=1)
                pooled.append(mean.cpu().numpy())

        vectors = np.concatenate(pooled, axis=0).astype(np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        if vectors.shape[1] != config.EMBEDDING_DIM:
            raise ValueError(
                f"Unexpected embedding dimension {vectors.shape[1]}; "
                f"expected {config.EMBEDDING_DIM} for {config.EMBEDDING_MODEL}."
            )
        return vectors


def load_embedder(model_name: str | None = None) -> MiniLMEmbedder:
    """Load (and cache) the embedder used across the pipeline."""
    model_name = model_name or config.EMBEDDING_MODEL
    if model_name not in _MODEL_CACHE:
        _MODEL_CACHE[model_name] = MiniLMEmbedder(model_name)
    return _MODEL_CACHE[model_name]


def embed_texts(
    texts: list[str],
    *,
    batch_size: int = 32,
    embedder: MiniLMEmbedder | None = None,
) -> np.ndarray:
    """Encode ``texts`` with the shared embedder -> (n, EMBEDDING_DIM) float32."""
    embedder = embedder or load_embedder()
    return embedder.encode(texts, batch_size=batch_size)


if __name__ == "__main__":
    emb = embed_texts(["Expense ratio of a mutual fund scheme"])
    print(f"Embedded 1 text -> shape={emb.shape} dtype={emb.dtype}")