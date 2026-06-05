"""HowBridge: extract skill candidates from experiences."""

from __future__ import annotations

from typing import Any

from rosclaw_darwin.evolution.skill_registry import SkillCandidate, SkillRegistry


class HowBridge:
    """Extract skills from recorded experiences using rule-based patterns."""

    def __init__(self):
        self.registry = SkillRegistry()

    def extract_skills(self, experiences: list[dict[str, Any]]) -> list[SkillCandidate]:
        """Extract skill candidates from experiences."""
        candidates: list[SkillCandidate] = []
        for exp in experiences:
            task_id = exp.get("task_id", "unknown")
            metrics = exp.get("metrics", {})
            # Simple rule: if success rate improved, infer skill
            if metrics.get("success_rate", 0.0) >= 0.2:
                # Create a generic skill candidate
                fp = "adaptive_grasp_skill"
                candidate = SkillCandidate(
                    id=f"skill_{task_id[:20]}",
                    name="adaptive_skill",
                    action_pattern=["observe", "adapt", "execute"],
                    affordances=[],
                    source_task_ids=[],
                    evidence={
                        "success_gain": metrics.get("success_rate", 0.0),
                        "progress_gain": metrics.get("progress_mean", 0.0),
                    },
                    fingerprint=fp,
                )
                candidates.append(candidate)
        return candidates
