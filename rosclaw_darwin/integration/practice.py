"""Bridge between Darwin evaluation and rosclaw-practice.

When an agent runs a task in Darwin, this bridge:
  1. Generates a PraxisEvent from the evaluation trajectory.
  2. Submits it to rosclaw-practice for MCAP recording and SeekDB persistence.

This enables the "practice → memory → evolution" loop.
"""

from __future__ import annotations

import os
import time
from typing import Any


class PracticeBridge:
    """Submit Darwin evaluation sessions as PraxisEvents to rosclaw-practice."""

    def __init__(self, mcap_dir: str | None = None, fallback_dir: str | None = None):
        self.mcap_dir = mcap_dir or os.getenv("ROSCLAW_PRACTICE_MCAP_DIR", "/data/rosclaw/mcap")
        self.fallback_dir = fallback_dir or os.getenv("ROSCLAW_PRACTICE_FALLBACK_DIR", "/data/rosclaw/fallback")
        self._committer: Any | None = None
        self._recorder: Any | None = None

    def _lazy_init(self) -> bool:
        """Try to import rosclaw_practice; return True if available."""
        if self._committer is not None:
            return True
        try:
            from rosclaw_practice.committer import ExperienceCommitter  # type: ignore[import-untyped]
            from rosclaw_practice.recorder import PhysicalRecorder  # type: ignore[import-untyped]

            self._committer = ExperienceCommitter(fallback_dir=self.fallback_dir)
            self._recorder = PhysicalRecorder(topics=["/darwin/eval"], base_dir=self.mcap_dir)
            return True
        except ImportError:
            return False

    def submit(
        self,
        session_id: str,
        task_id: str,
        metrics: dict[str, Any],
        robot_id: str = "darwin_agent",
        semantic_intent: str = "",
        llm_cot: str = "",
    ) -> dict[str, Any]:
        """Build and submit a PraxisEvent.

        Returns the event dict (whether submission succeeded or fell back).
        """
        event = {
            "practice_id": session_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "robot_id": robot_id,
            "cognitive_context": {
                "semantic_intent": semantic_intent or f"Evaluate task {task_id}",
                "llm_cot": llm_cot or "Darwin evaluation loop",
            },
            "physical_feedback": {
                "status": "SUCCESS" if metrics.get("success") else "FAILED_EVAL",
                "reward": 1.0 if metrics.get("success") else 0.0,
                "error_log": metrics.get("info", {}).get("error", ""),
            },
            "data_pointers": {
                "mcap_path": f"{self.mcap_dir}/{session_id}.mcap",
            },
        }

        if self._lazy_init():
            try:
                self._committer.save_to_seekdb(event)
                event["_submitted"] = True
            except Exception as exc:
                event["_submitted"] = False
                event["_error"] = str(exc)
        else:
            event["_submitted"] = False
            event["_reason"] = "rosclaw_practice not installed"

        return event
