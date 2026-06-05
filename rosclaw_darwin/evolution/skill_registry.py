"""Skill registry: discover and validate reusable skills."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from rosclaw_darwin.tdl.fingerprints import primitive_fingerprint
from rosclaw_darwin.tdl.schema import Task


class SkillCandidate(BaseModel):
    id: str
    name: str
    action_pattern: list[str]
    affordances: list[str]
    preconditions: list[str] = []
    postconditions: list[str] = []
    source_task_ids: list[str] = []
    evidence: dict = {}
    fingerprint: str


class SkillRegistry:
    """Registry of validated skills discovered during evolution."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._skills: dict[str, SkillCandidate] = {}
        self._candidates: dict[str, SkillCandidate] = {}
        self._min_task_count = self.config.get("min_task_count", 1)
        self._min_success_gain = self.config.get("min_success_gain", 0.10)
        self._min_progress_gain = self.config.get("min_progress_gain", 0.15)

    def exists(self, fingerprint: str) -> bool:
        return fingerprint in self._skills

    def add_candidate(self, candidate: SkillCandidate) -> None:
        """Record a candidate regardless of validation status."""
        self._candidates[candidate.fingerprint] = candidate

    def add(self, candidate: SkillCandidate) -> bool:
        self.add_candidate(candidate)
        # Merge source_task_ids if fingerprint already exists
        existing = self._skills.get(candidate.fingerprint)
        if existing is not None:
            merged_ids = list(set(existing.source_task_ids + candidate.source_task_ids))
            existing.source_task_ids = merged_ids
            # Re-evaluate reusability after merge
            if len(merged_ids) >= self._min_task_count:
                return True
            return False
        if self.is_valid_new_skill(candidate):
            self._skills[candidate.fingerprint] = candidate
            return True
        return False

    def is_valid_new_skill(self, candidate: SkillCandidate) -> bool:
        novelty = not self.exists(candidate.fingerprint)
        reusability = len(set(candidate.source_task_ids)) >= self._min_task_count
        effectiveness = (
            candidate.evidence.get("success_gain", 0.0) >= self._min_success_gain
            or candidate.evidence.get("progress_gain", 0.0) >= self._min_progress_gain
        )
        return novelty and reusability and effectiveness

    def candidate_count(self) -> int:
        return len(self._candidates)

    def validated_count(self) -> int:
        return len(self._skills)

    def list_skills(self) -> list[SkillCandidate]:
        return list(self._skills.values())

    def list_candidates(self) -> list[SkillCandidate]:
        return list(self._candidates.values())

    def extract_from_task(self, task: Task) -> list[SkillCandidate]:
        """Rule-based skill extraction from task primitives."""
        candidates: list[SkillCandidate] = []
        primitives = [p.name for p in task.primitives]
        affordances = []
        for o in task.objects:
            affordances.extend(str(a) for a in o.affordances)
        affordances = list(set(affordances))

        # Open skill
        if any("grasp" in p or "open" in p for p in primitives):
            fp = primitive_fingerprint("open", affordances)
            candidates.append(SkillCandidate(
                id=f"skill_open_{fp[:8]}",
                name="open",
                action_pattern=["grasp(handle)", "pull/rotate", "object_state_open"],
                affordances=["openable", "articulated"],
                preconditions=["near(handle)", "gripper_free"],
                postconditions=["is_open(object)"],
                source_task_ids=[task.id],
                fingerprint=fp,
            ))

        # Pick skill
        if any("grasp" in p or "pick" in p for p in primitives):
            fp = primitive_fingerprint("pick", affordances)
            candidates.append(SkillCandidate(
                id=f"skill_pick_{fp[:8]}",
                name="pick",
                action_pattern=["approach", "grasp", "lift", "object_held"],
                affordances=["graspable", "movable"],
                preconditions=["near(object)", "gripper_free"],
                postconditions=["holding(object)"],
                source_task_ids=[task.id],
                fingerprint=fp,
            ))

        # Place skill
        if any("place" in p for p in primitives):
            fp = primitive_fingerprint("place", affordances)
            candidates.append(SkillCandidate(
                id=f"skill_place_{fp[:8]}",
                name="place",
                action_pattern=["move", "release", "object_on_target"],
                affordances=["surface", "container"],
                preconditions=["holding(object)"],
                postconditions=["on(object, target)"],
                source_task_ids=[task.id],
                fingerprint=fp,
            ))

        # Press skill
        if any("press" in p for p in primitives):
            fp = primitive_fingerprint("press", affordances)
            candidates.append(SkillCandidate(
                id=f"skill_press_{fp[:8]}",
                name="press",
                action_pattern=["align", "push", "button_state_changed"],
                affordances=["pressable"],
                preconditions=["near(button)"],
                postconditions=["is_pressed(button)"],
                source_task_ids=[task.id],
                fingerprint=fp,
            ))

        # Recover skill
        if any("retry" in p or "recover" in p for p in primitives):
            fp = primitive_fingerprint("recover", affordances)
            candidates.append(SkillCandidate(
                id=f"skill_recover_{fp[:8]}",
                name="recover",
                action_pattern=["failure", "retry", "success"],
                affordances=[],
                preconditions=["failure_detected"],
                postconditions=["task_resumed"],
                source_task_ids=[task.id],
                fingerprint=fp,
            ))

        return candidates

    def to_dict(self) -> dict[str, Any]:
        return {
            "skills": [s.model_dump(mode="json") for s in self._skills.values()],
            "config": self.config,
        }
