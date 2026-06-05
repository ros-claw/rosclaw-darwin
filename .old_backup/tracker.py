"""MemoryEvolutionTracker: verify that SeekDB learned the right lessons.

After EvolutionRunner finishes both loops, the tracker:
  1. Queries SeekDB for causal edges formed during consolidation.
  2. Checks whether failure patterns were correctly recognised.
  3. Validates that skill templates were extracted.
"""

from __future__ import annotations

from typing import Any

from rosclaw_darwin.integration.memory import MemoryBridge


class MemoryEvolutionTracker:
    """Post-hoc verification of memory formation after evolution evaluation."""

    def __init__(self, memory: MemoryBridge | None = None):
        self.memory = memory or MemoryBridge()

    def verify(
        self,
        task_id: str,
        before_session: str,
        after_session: str,
    ) -> dict[str, Any]:
        """Run all verification checks and return a structured report.

        Returns:
            {
                "task_id": str,
                "passed": bool,
                "checks": {
                    "causal_edge_present": bool,
                    "failure_pattern_recognised": bool,
                    "skill_template_extracted": bool,
                },
                "details": dict,
            }
        """
        report: dict[str, Any] = {
            "task_id": task_id,
            "passed": False,
            "checks": {},
            "details": {},
        }

        # Check 1: Did SeekDB form a causal edge between the failure and the correction?
        causal = self.memory.verify_evolution(task_id, before_session, after_session)
        report["checks"]["causal_edge_present"] = causal.get("improved", False)
        report["details"]["causal"] = causal

        # Check 2: Query for failure-pattern recognition.
        before_mem = self.memory.query(f"task_id:{task_id} session_id:{before_session}", n_results=1)
        after_mem = self.memory.query(f"task_id:{task_id} session_id:{after_session}", n_results=1)
        report["checks"]["failure_pattern_recognised"] = self._has_pattern_recognition(
            before_mem, after_mem
        )
        report["details"]["before_memories"] = before_mem
        report["details"]["after_memories"] = after_mem

        # Check 3: Skill template extraction (heuristic: did the agent complete faster?)
        report["checks"]["skill_template_extracted"] = self._has_skill_template(
            before_mem, after_mem
        )

        report["passed"] = all(report["checks"].values())
        return report

    @staticmethod
    def _has_pattern_recognition(before: list[dict], after: list[dict]) -> bool:
        """Heuristic: if 'after' memories exist and differ from 'before', recognition occurred."""
        if not before or not after:
            return False
        b_text = before[0].get("text", "")
        a_text = after[0].get("text", "")
        return b_text != a_text and len(a_text) > len(b_text)

    @staticmethod
    def _has_skill_template(before: list[dict], after: list[dict]) -> bool:
        """Heuristic: if after shows improvement metadata, a skill template was formed."""
        if not after:
            return False
        meta = after[0].get("metadata", {})
        return meta.get("outcome") == "success"
