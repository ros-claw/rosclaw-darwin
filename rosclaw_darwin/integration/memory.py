"""MemoryBridge: record and query experiences."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.tdl.schema import Task


class MemoryBridge:
    """File-based memory bridge for experiences."""

    def __init__(self, mode: str = "file", path: str | None = None):
        self.mode = mode
        self._path = Path(path) if path else Path("data/memory/darwin_experiences.jsonl")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            import tempfile
            self._path = Path(tempfile.gettempdir()) / "rosclaw_darwin" / "darwin_experiences.jsonl"
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record_experience(self, task: Task, result: EvaluationResult) -> str:
        record = {
            "task_id": task.id,
            "run_id": result.run_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metrics": result.metrics,
            "failure_types": result.failure_types,
            "adapter": result.adapter,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return result.run_id

    def query_experiences(
        self,
        task: Task,
        failure_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        results: list[dict[str, Any]] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("task_id") == task.id:
                        if failure_type is None or failure_type in rec.get("failure_types", {}):
                            results.append(rec)
                except json.JSONDecodeError:
                    continue
        return results

    def consolidate(self, task: Task) -> dict[str, Any]:
        """Consolidate experiences for a task and compute memory bonus."""
        experiences = self.query_experiences(task)
        if not experiences:
            return {"memory_bonus": 0.0, "count": 0}

        # Simple heuristic: if previous failures exist, provide memory bonus
        failures = sum(1 for e in experiences if e.get("metrics", {}).get("success_rate", 1.0) < 0.5)
        memory_bonus = min(0.3, 0.05 * failures)
        return {
            "memory_bonus": memory_bonus,
            "count": len(experiences),
            "failures": failures,
        }
