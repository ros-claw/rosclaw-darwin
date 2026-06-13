"""Mock adapter for CI and local development without GPU."""

from __future__ import annotations

import random
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.tdl.schema import Task

from .base import BaseEnvironmentAdapter


class MockAdapter(BaseEnvironmentAdapter):
    """Mock environment that simulates success rates based on difficulty and policy strength."""

    name = "mock"

    def __init__(self, task: Task, **kwargs: Any):
        super().__init__(task, **kwargs)
        self._step_count = 0
        self._episode = 0
        self._max_steps = task.eval.max_steps or 1000

    def build(self) -> None:
        self._env = {"built": True}

    def reset(self) -> dict:
        self._step_count = 0
        return {"obs": "mock_obs", "task_id": self.task.id}

    def step(self, action: Any) -> tuple[dict, float, bool, dict]:
        self._step_count += 1
        terminated = self._step_count >= self._max_steps
        info = {"step": self._step_count, "mock": True}
        return {"obs": "mock_obs"}, 0.0, terminated, info

    def run_policy(
        self,
        policy_config: dict,
        episodes: int | None = None,
    ) -> EvaluationResult:
        """Simulate policy execution with configurable success probability."""
        from rosclaw_darwin.evaluation.metrics import compute_basic_metrics

        eps = episodes or self.task.eval.max_episodes or 20
        difficulty = self.task.mutation.difficulty
        strength = policy_config.get("strength", 0.5)
        memory_bonus = policy_config.get("memory_bonus", 0.0)
        skill_hints = policy_config.get("skill_hints", [])

        # Skill transfer bonus: relevant skill hints improve mock success probability.
        task_primitives = {p.name.lower() for p in self.task.primitives}
        manipulation_primitives = {"pick", "place", "open", "close", "grasp", "lift"}
        skill_bonus = 0.0
        for hint in skill_hints:
            hint_lower = hint.lower()
            if hint_lower in task_primitives or (
                hint_lower in {"grasp_adjust", "efficient_execution", "adaptive_skill"}
                and task_primitives & manipulation_primitives
            ):
                skill_bonus += 0.15
        skill_bonus = min(skill_bonus, 0.3)

        # Compute success probability
        success_prob = max(0.0, min(1.0, strength + memory_bonus + skill_bonus - 0.1 * difficulty))
        rng = random.Random(self.task.mutation.seed)

        results: list[dict] = []
        failure_types: dict[str, int] = {}

        base_time = 5.0
        for ep in range(eps):
            success = rng.random() < success_prob
            if not success:
                ft = self._infer_failure_type(rng)
                failure_types[ft] = failure_types.get(ft, 0) + 1
            steps = rng.randint(50, self._max_steps) if success else self._max_steps
            deterministic_time = base_time + difficulty * 2.0 + (steps * 0.05)
            jitter = (ep % 5) * 0.01
            results.append({
                "success": success,
                "steps": steps,
                "collisions": rng.randint(0, 5) if not success else rng.randint(0, 2),
                "time": deterministic_time + jitter,
            })

        metrics = compute_basic_metrics(results)
        run_id = f"mock_{rng.randint(10000000, 99999999):x}"

        return EvaluationResult(
            run_id=run_id,
            task_id=self.task.id,
            policy_id=policy_config.get("policy_id", "mock_policy"),
            adapter=self.name,
            status="completed",
            metrics=metrics,
            failure_types=failure_types,
            metadata={
                "success_prob": success_prob,
                "difficulty": difficulty,
                "strength": strength,
                "memory_bonus": memory_bonus,
                "episodes": eps,
            },
        )

    def _infer_failure_type(self, rng: random.Random) -> str:
        primitives = [p.name for p in self.task.primitives]
        candidates = ["timeout"]
        if any("grasp" in p or "pick" in p for p in primitives):
            candidates.append("grasp_failed")
        if any("open" in p for p in primitives):
            candidates.append("handle_grasp_failed")
            candidates.append("door_not_opened")
        if any("navigate" in p for p in primitives):
            candidates.append("navigation_failed")
        if any("place" in p for p in primitives):
            candidates.append("object_dropped")
        return rng.choice(candidates)

    def close(self) -> None:
        self._env = None
