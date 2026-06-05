"""PracticeBridge: submit evaluation events."""

from __future__ import annotations

import json
import time
from pathlib import Path

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.tdl.schema import Task


class PracticeBridge:
    """Submit Darwin evaluation sessions as practice events."""

    def __init__(self, mode: str = "file", endpoint: str | None = None):
        self.mode = mode
        self.endpoint = endpoint
        self._events_dir = Path("data/practice_events")
        try:
            self._events_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            import tempfile
            self._events_dir = Path(tempfile.gettempdir()) / "rosclaw_darwin" / "practice_events"
            self._events_dir.mkdir(parents=True, exist_ok=True)

    def submit_event(self, result: EvaluationResult, task: Task) -> dict:
        event = {
            "practice_id": result.run_id,
            "task_id": task.id,
            "robot_id": task.embodiment.robot,
            "status": "SUCCESS" if result.metrics.get("success_rate", 0.0) > 0.5 else "FAILED",
            "reward": result.metrics.get("success_rate", 0.0),
            "failure_type": self._dominant_failure(result),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metrics": result.metrics,
        }

        if self.mode == "file":
            path = self._events_dir / "events.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        elif self.mode == "http" and self.endpoint:
            import urllib.request
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(event).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

        return event

    @staticmethod
    def _dominant_failure(result: EvaluationResult) -> str:
        if not result.failure_types:
            return ""
        return max(result.failure_types, key=result.failure_types.get)  # type: ignore[arg-type]
