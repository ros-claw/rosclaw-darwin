"""Evaluator: run policies in environments and produce results."""

from __future__ import annotations

import time
import uuid
from typing import Any

from rosclaw_darwin.evaluation.metrics import compute_basic_metrics
from rosclaw_darwin.evaluation.result import EvaluationResult


class Evaluator:
    """Evaluate a policy against an adapter."""

    def __init__(self, adapter):
        self.adapter = adapter

    def evaluate_policy(
        self,
        policy_config: dict[str, Any],
        episodes: int | None = None,
    ) -> EvaluationResult:
        """Run policy evaluation."""
        if not self.adapter.is_built:
            self.adapter.build()

        task = self.adapter.task
        eps = episodes or task.eval.max_episodes or 20
        run_id = f"eval_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        results: list[dict] = []
        for _ in range(eps):
            obs = self.adapter.reset()
            done = False
            step = 0
            max_steps = task.eval.max_steps or 1000
            success = False
            collisions = 0

            while not done and step < max_steps:
                action = self._get_action(obs, policy_config)
                obs, reward, terminated, info = self.adapter.step(action)
                step += 1
                done = terminated
                if info.get("collision"):
                    collisions += 1
                if info.get("success") or reward > 0.9:
                    success = True

            results.append({
                "success": success,
                "steps": step,
                "collisions": collisions,
                "time": step * 0.05,
            })

        metrics = compute_basic_metrics(results)
        return EvaluationResult(
            run_id=run_id,
            task_id=task.id,
            policy_id=policy_config.get("policy_id", "unknown"),
            adapter=self.adapter.name,
            status="completed",
            metrics=metrics,
        )

    @staticmethod
    def _get_action(obs: dict, policy_config: dict) -> Any:
        policy_type = policy_config.get("type", "zero")
        if policy_type == "zero":
            return {"x": 0.0, "y": 0.0, "z": 0.0, "gripper": 1.0}
        if policy_type == "random":
            import random
            return {
                "x": random.uniform(-0.1, 0.1),
                "y": random.uniform(-0.1, 0.1),
                "z": random.uniform(-0.05, 0.05),
                "gripper": random.choice([-1.0, 1.0]),
            }
        if policy_type == "replay":
            return policy_config.get("actions", [{}])[0]
        return {}
