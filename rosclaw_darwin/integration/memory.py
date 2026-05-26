"""Bridge between Darwin evaluation and rosclaw-memory (SeekDB).

Darwin uses this bridge to:
  1. Query past experiences before evaluation (contextual priming).
  2. Verify memory formation after evaluation (evolution tracking).
"""

from __future__ import annotations

import os
from typing import Any


class MemoryBridge:
    """Query and verify SeekDB collections for evolutionary analysis."""

    def __init__(self, mode: str | None = None):
        self.mode = (mode or os.getenv("SEEKDB_MODE", "embedded")).strip().lower()
        self._client: Any | None = None

    def _lazy_init(self) -> bool:
        if self._client is not None:
            return True
        try:
            import pyseekdb  # type: ignore[import-untyped]
            if self.mode == "server":
                self._client = pyseekdb.RemoteServerClient(
                    host=os.getenv("SEEKDB_HOST", "localhost"),
                    port=int(os.getenv("SEEKDB_PORT", "2881")),
                    tenant=os.getenv("SEEKDB_TENANT", "rosclaw"),
                    database=os.getenv("SEEKDB_DATABASE", "rosclaw_darwin"),
                )
            else:
                path = os.getenv("SEEKDB_PATH", "/data/seekdb/darwin")
                os.makedirs(path, exist_ok=True)
                self._client = pyseekdb.Client(path=path, database="rosclaw_darwin")
            return True
        except ImportError:
            return False

    def query(self, query_text: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Search SeekDB for experiences related to query_text."""
        if not self._lazy_init():
            return []
        try:
            col = self._client.get_or_create_collection(name="darwin_experiences")
            results = col.query(query_texts=[query_text], n_results=n_results)
            # Normalise pyseekdb result shape to a flat list of dicts.
            memories: list[dict[str, Any]] = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for d, m, dist in zip(docs, metas, dists):
                memories.append({"text": d, "metadata": m, "distance": dist})
            return memories
        except Exception as exc:
            return [{"error": str(exc)}]

    def record_experience(
        self,
        task_id: str,
        session_id: str,
        outcome: str,
        metrics: dict[str, Any],
    ) -> bool:
        """Write an evaluation outcome into SeekDB for future retrieval."""
        if not self._lazy_init():
            return False
        try:
            col = self._client.get_or_create_collection(name="darwin_experiences")
            text = f"Task {task_id}: {outcome}. Steps={metrics.get('step_count', 0)} Success={metrics.get('success', False)}"
            col.add(
                documents=[text],
                metadatas=[{"task_id": task_id, "session_id": session_id, "outcome": outcome}],
                ids=[session_id],
            )
            return True
        except Exception:
            return False

    def verify_evolution(
        self,
        task_id: str,
        before_session: str,
        after_session: str,
    ) -> dict[str, Any]:
        """Check whether the after_session shows improvement over before_session.

        Returns a dict with keys:
            improved: bool
            delta: float          # metric improvement
            causal_edges: list    # newly formed causal edges in SeekDB
        """
        if not self._lazy_init():
            return {"improved": False, "delta": 0.0, "causal_edges": [], "error": "SeekDB unavailable"}

        before = self.query(f"task_id:{task_id} session_id:{before_session}", n_results=1)
        after = self.query(f"task_id:{task_id} session_id:{after_session}", n_results=1)

        if not before or not after:
            return {"improved": False, "delta": 0.0, "causal_edges": [], "error": "Missing sessions"}

        b_meta = before[0].get("metadata", {})
        a_meta = after[0].get("metadata", {})
        b_success = b_meta.get("outcome") == "success"
        a_success = a_meta.get("outcome") == "success"
        improved = (not b_success) and a_success

        return {
            "improved": improved,
            "delta": 1.0 if improved else 0.0,
            "causal_edges": [],
        }
