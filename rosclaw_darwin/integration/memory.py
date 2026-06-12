"""MemoryBridge: record and query experiences."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.integration.memory_store import MemoryStore
from rosclaw_darwin.tdl.schema import Task


class MemoryBridge:
    """File-based memory bridge for experiences.

    Records are persisted to a global JSONL store (for cross-task retrieval)
    and optionally flushed to a per-run directory (for self-contained reports).
    """

    def __init__(self, mode: str = "file", path: str | None = None, embedding_model: str | None = None):
        self.mode = mode
        self._session_records: list[dict[str, Any]] = []
        self._path = Path(path) if path else Path("data/memory/darwin_experiences.jsonl")
        self.store = MemoryStore(
            self._path,
            backend=mode,
            embedding_model=embedding_model,
        )

    def record_experience(
        self,
        task: Task,
        result: EvaluationResult,
        evolution_run_id: str | None = None,
    ) -> str:
        record = {
            "task_id": task.id,
            "task_name": task.name,
            "run_id": result.run_id,
            "evolution_run_id": evolution_run_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metrics": result.metrics,
            "failure_types": result.failure_types,
            "adapter": result.adapter,
            "task_text": task.description or "",
        }
        self.store.record(record)
        self._session_records.append(record)
        return result.run_id

    def query_experiences(
        self,
        task: Task,
        failure_type: str | None = None,
        evolution_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.query(
            task_id=task.id,
            failure_type=failure_type,
            evolution_run_id=evolution_run_id,
        )

    def query_similar_experiences(
        self,
        text: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return experiences semantically similar to ``text``."""
        return self.store.query_similar(text, top_k=top_k)

    def consolidate(self, task: Task) -> dict[str, Any]:
        """Consolidate experiences for a task and compute memory bonus."""
        return self.store.consolidate(task_id=task.id)

    def finalize(self, run_dir: str | Path | None = None) -> None:
        """Flush the current session's records into the run directory.

        This makes an evolution report self-contained even though the global
        memory store may contain experiences from many runs.
        """
        if run_dir is None or not self._session_records:
            return
        run_store = MemoryStore(Path(run_dir) / "memory" / "experiences.jsonl", backend="file")
        for record in self._session_records:
            run_store.record(record)

    def count(self) -> int:
        return self.store.count()
