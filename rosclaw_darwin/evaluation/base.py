"""Base evaluator and the DarwinEvaluator that runs full evaluation loops."""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from rosclaw_darwin.tdl.schema import Task
from rosclaw_darwin.environment.base import BaseEnvironmentAdapter
from .metrics import EvaluationMetrics, compute_metrics


class BaseEvaluator:
    """Run a task in a simulator and produce metrics."""

    def __init__(self, adapter: BaseEnvironmentAdapter):
        self.adapter = adapter
        self.results: list[EvaluationMetrics] = []

    def evaluate(
        self,
        policy: Callable[[dict[str, Any]], Any],
        max_steps: int | None = None,
    ) -> EvaluationMetrics:
        """Evaluate one episode.

        Args:
            policy: Callable(obs) -> action (dict, tensor, or array).
            max_steps: Override the task's max_steps if provided.
        """
        if not self.adapter.is_built:
            self.adapter.build()

        task = self.adapter.task
        limit = max_steps or task.eval_config.max_steps

        obs = self.adapter.reset()
        trajectory: list[dict[str, Any]] = []
        success = False
        t0 = time.perf_counter()

        for step in range(limit):
            action = policy(obs)
            obs, reward, terminated, truncated, info = self.adapter.step(action)

            trajectory.append({
                "step": step,
                "obs": obs,
                "action": action,
                "reward": reward,
                "info": info,
            })

            if terminated or truncated:
                success = info.get("success", reward > 0.9)
                break

        elapsed = time.perf_counter() - t0
        metrics = compute_metrics(trajectory, success=success)
        metrics.completion_time = elapsed
        self.results.append(metrics)
        return metrics

    def evaluate_repeated(
        self,
        policy: Callable[[dict[str, Any]], Any],
        n: int = 1,
    ) -> list[EvaluationMetrics]:
        """Run n independent episodes and return all metrics."""
        out: list[EvaluationMetrics] = []
        for _ in range(n):
            m = self.evaluate(policy)
            out.append(m)
        return out

    def aggregate(self) -> dict[str, Any]:
        """Aggregate results across all episodes."""
        if not self.results:
            return {}
        successes = sum(1 for r in self.results if r.success)
        return {
            "episodes": len(self.results),
            "success_rate": successes / len(self.results),
            "avg_completion_time": sum(r.completion_time for r in self.results) / len(self.results),
            "avg_collision_count": sum(r.collision_count for r in self.results) / len(self.results),
            "avg_step_count": sum(r.step_count for r in self.results) / len(self.results),
        }


class DarwinEvaluator(BaseEvaluator):
    """Extended evaluator that integrates with rosclaw-practice and memory.

    During evaluation it captures PraxisEvents via the practice decorator,
    and after evaluation it queries SeekDB for evolutionary analysis.
    """

    def __init__(
        self,
        adapter: BaseEnvironmentAdapter,
        practice_hook: Callable | None = None,
        memory_hook: Callable | None = None,
    ):
        super().__init__(adapter)
        self.practice_hook = practice_hook
        self.memory_hook = memory_hook
        self.session_id = f"darwin_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    def evaluate(
        self,
        policy: Callable[[dict[str, Any]], Any],
        max_steps: int | None = None,
    ) -> EvaluationMetrics:
        """Evaluate with practice capture and memory integration."""
        metrics = super().evaluate(policy, max_steps=max_steps)

        # Trigger practice capture if available
        if self.practice_hook:
            try:
                self.practice_hook(
                    session_id=self.session_id,
                    task_id=self.adapter.task.id,
                    metrics=metrics.to_dict(),
                )
            except Exception:
                pass

        # Query memory for related past experiences
        if self.memory_hook:
            try:
                memories = self.memory_hook(query_text=self.adapter.task.id)
                metrics.info["related_memories"] = memories
            except Exception:
                pass

        return metrics
