"""EvolutionRunner: the core loop that measures how fast an agent evolves."""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any

from pydantic import BaseModel

from rosclaw_darwin.adapters.base import BaseEnvironmentAdapter
from rosclaw_darwin.evaluation.metrics import compute_evolution_metrics
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evolution.skill_registry import SkillCandidate, SkillRegistry
from rosclaw_darwin.integration.how import HowBridge
from rosclaw_darwin.integration.memory import MemoryBridge
from rosclaw_darwin.integration.practice import PracticeBridge
from rosclaw_darwin.tdl.schema import Task


class EvolutionReport(BaseModel):
    run_id: str
    task_id: str
    policy_id: str
    loop_results: list[EvaluationResult]
    evolution_metrics: dict[str, float]
    discovered_skills: list[SkillCandidate] = []
    generated_tasks: list[str] = []
    artifacts: dict = {}




class EvolutionRunner:
    """Run the two-loop evolution evaluation for a single agent + task."""

    def __init__(
        self,
        adapter: BaseEnvironmentAdapter,
        practice_bridge=None,
        memory_bridge=None,
        how_bridge=None,
        config=None,
    ):
        self.adapter = adapter
        self.practice = practice_bridge or PracticeBridge()
        self.memory = memory_bridge or MemoryBridge()
        self.how = how_bridge or HowBridge()
        self.config = config or {}
        self.skill_registry = SkillRegistry(self.config.get("skill_discovery"))

    def evolve(
        self,
        task: Task,
        policy_config: dict,
        loops: int = 2,
        episodes: int | None = None,
    ) -> dict[str, Any]:
        """Run the full evolution loop.

        Returns EvolutionReport as dict.
        """
        run_id = f"evo_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        loop_results: list[EvaluationResult] = []

        # --- Loop 1: First Encounter ---
        result1 = self.adapter.run_policy(policy_config, episodes=episodes)
        loop_results.append(result1)

        # Practice event
        self.practice.submit_event(result1, task)

        # Memory record
        self.memory.record_experience(task, result1)

        # How: skill extraction
        experiences = self.memory.query_experiences(task)
        candidates = self.how.extract_skills(experiences)
        for c in candidates:
            c.source_task_ids.append(task.id)
            self.skill_registry.add(c)

        # Mutate / generate follow-up tasks
        generated_tasks: list[str] = []
        if not result1.metrics.get("success_rate", 0.0) >= 0.8:
            from rosclaw_darwin.evolution.mutators import MUTATOR_REGISTRY
            mutator_names = task.mutation.allowed or ["spatial", "object", "constraint"]
            for mname in mutator_names[:2]:
                mutator_cls = MUTATOR_REGISTRY.get(mname)
                if mutator_cls:
                    mutated = mutator_cls().mutate(task, seed=task.mutation.seed)
                    generated_tasks.append(mutated.id)

        # Consolidation: add memory bonus for loop 2
        consolidated = self.memory.consolidate(task)
        memory_bonus = consolidated.get("memory_bonus", 0.0)

        # --- Loop 2: Retry after learning ---
        policy2 = copy.deepcopy(policy_config)
        policy2["memory_bonus"] = memory_bonus
        result2 = self.adapter.run_policy(policy2, episodes=episodes)
        loop_results.append(result2)

        self.practice.submit_event(result2, task)
        self.memory.record_experience(task, result2)

        # Evolution metrics
        l1 = {
            **result1.metrics,
            "num_failures": (task.eval.max_episodes or 20) - int(result1.metrics.get("num_success", 0)),
        }
        l2 = {
            **result2.metrics,
            "num_failures": (task.eval.max_episodes or 20) - int(result2.metrics.get("num_success", 0)),
        }
        evo_metrics = compute_evolution_metrics(l1, l2)

        # Skill discovery rate from registry
        evo_metrics["skill_discovery_rate"] = len(self.skill_registry.list_skills()) / max(1, len(loop_results))

        report = {
            "run_id": run_id,
            "task_id": task.id,
            "policy_id": policy_config.get("policy_id", "unknown"),
            "loop_results": [r.model_dump(mode="json") for r in loop_results],
            "evolution_metrics": evo_metrics,
            "discovered_skills": [s.model_dump(mode="json") for s in self.skill_registry.list_skills()],
            "generated_tasks": generated_tasks,
            "artifacts": {},
        }
        return report
