"""Persistent experience store with optional vector indexing."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    """Protocol for text embedding providers."""

    def encode(self, text: str) -> list[float]:
        ...


class SentenceTransformerEmbedding:
    """sentence-transformers backed embedding provider."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def encode(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()


class KeywordEmbedding:
    """Lightweight deterministic keyword embedding fallback.

    Uses hashed token counts to produce a fixed-size unit vector.  This avoids
    any heavy dependencies while still supporting cosine-similarity search.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def encode(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in self._tokens(text):
            idx = hash(token) % self.dim
            vec[idx] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower()) if text else []


def _resolve_embedding_provider(model: str | None) -> EmbeddingProvider:
    """Resolve embedding provider name to instance."""
    if model == "sentence_transformer":
        try:
            return SentenceTransformerEmbedding()
        except Exception:
            return KeywordEmbedding()
    if model is None or model == "keyword":
        return KeywordEmbedding()
    if model == "none":
        return KeywordEmbedding()
    return KeywordEmbedding()


class MemoryStore:
    """Persistent store for evaluation experiences.

    Supports two backends:
    * ``file`` -- JSONL persistence with keyword similarity search.
    * ``vector`` -- JSONL persistence plus an in-memory vector index that
      enables semantic ``query_similar``.  Embeddings are recomputed on load so
      the store remains portable.
    """

    def __init__(
        self,
        path: str | Path,
        backend: str = "file",
        embedding_model: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.backend = backend
        self.embedding_provider = _resolve_embedding_provider(embedding_model)
        self._records: list[dict[str, Any]] = []
        self._embeddings: np.ndarray | None = None
        self._ensure_path()
        self._load()

    def _ensure_path(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            import tempfile

            self.path = Path(tempfile.gettempdir()) / "rosclaw_darwin" / self.path.name
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._records.append(record)
        self._rebuild_embeddings()

    def _rebuild_embeddings(self) -> None:
        if self.backend != "vector" or not self._records:
            self._embeddings = None
            return
        vectors = [np.array(self._embedding_vector(r), dtype=np.float32) for r in self._records]
        self._embeddings = np.vstack(vectors)

    def _record_text(self, record: dict[str, Any]) -> str:
        parts = [
            str(record.get("task_id", "")),
            str(record.get("task_name", "")),
            str(record.get("adapter", "")),
            " ".join(str(k) for k in record.get("failure_types", {}).keys()),
            str(record.get("task_text", "")),
        ]
        return " ".join(p for p in parts if p)

    def _embedding_vector(self, record: dict[str, Any]) -> list[float]:
        return self.embedding_provider.encode(self._record_text(record))

    def record(self, record: dict[str, Any]) -> None:
        """Append a record to the store and persist it."""
        if "timestamp" not in record:
            record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if self.backend == "vector":
            record["embedding"] = self._embedding_vector(record)
            vec = np.array(record["embedding"], dtype=np.float32).reshape(1, -1)
            if self._embeddings is None:
                self._embeddings = vec
            else:
                self._embeddings = np.vstack([self._embeddings, vec])

        self._records.append(record)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def count(self) -> int:
        return len(self._records)

    def query(
        self,
        task_id: str | None = None,
        failure_type: str | None = None,
        run_id: str | None = None,
        evolution_run_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Filter records by exact metadata fields."""
        results: list[dict[str, Any]] = []
        for rec in self._records:
            if task_id is not None and rec.get("task_id") != task_id:
                continue
            if run_id is not None and rec.get("run_id") != run_id:
                continue
            if evolution_run_id is not None and rec.get("evolution_run_id") != evolution_run_id:
                continue
            if failure_type is not None and failure_type not in rec.get("failure_types", {}):
                continue
            results.append(rec)
            if limit is not None and len(results) >= limit:
                break
        return results

    def query_similar(
        self,
        text: str,
        top_k: int = 5,
        exclude_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the top-k records most similar to ``text``.

        Uses the vector index when available, otherwise falls back to keyword
        overlap.
        """
        if not self._records:
            return []

        if self.backend == "vector" and self._embeddings is not None:
            scores = self._vector_scores(text)
        else:
            scores = self._keyword_scores(text)

        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for idx, _score in indexed:
            rec = self._records[idx]
            if exclude_run_id is not None and rec.get("run_id") == exclude_run_id:
                continue
            results.append(rec)
            if len(results) >= top_k:
                break
        return results

    def _vector_scores(self, text: str) -> list[float]:
        query_vec = np.array(self.embedding_provider.encode(text), dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return [0.0] * len(self._records)
        query_vec = query_vec / query_norm
        norms = np.linalg.norm(self._embeddings, axis=1)
        safe_norms = np.where(norms == 0, 1.0, norms)
        similarities = (self._embeddings / safe_norms[:, None]) @ query_vec
        return [float(s) for s in similarities]

    def _keyword_scores(self, text: str) -> list[float]:
        query_tokens = self._token_set(text)
        scores: list[float] = []
        for rec in self._records:
            record_tokens = self._token_set(self._record_text(rec))
            denom = max(len(query_tokens), len(record_tokens), 1)
            scores.append(len(query_tokens & record_tokens) / denom)
        return scores

    @staticmethod
    def _token_set(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.lower())) if text else set()

    def consolidate(self, task_id: str | None = None) -> dict[str, Any]:
        """Aggregate experiences and compute a memory bonus."""
        experiences = self.query(task_id=task_id)
        if not experiences:
            return {"memory_bonus": 0.0, "count": 0, "failures": 0}
        failures = sum(
            1 for e in experiences if e.get("metrics", {}).get("success_rate", 1.0) < 0.5
        )
        memory_bonus = min(0.3, 0.05 * failures)
        return {
            "memory_bonus": memory_bonus,
            "count": len(experiences),
            "failures": failures,
        }
