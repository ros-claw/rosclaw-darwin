"""Base adapter interface for all environment backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.tdl.schema import Task


class BaseEnvironmentAdapter(ABC):
    """Abstract base for simulator adapters."""

    name: str = "base"

    def __init__(self, task: Task, **kwargs: Any):
        self.task = task
        self.config = kwargs
        self._env: Any | None = None

    @abstractmethod
    def build(self) -> None:
        """Construct the simulator environment from the Task definition."""

    @abstractmethod
    def reset(self) -> dict:
        """Reset the environment; return initial observation."""

    @abstractmethod
    def step(self, action: Any) -> tuple[dict, float, bool, dict]:
        """Execute one action. Returns observation, reward, terminated, info."""

    def run_policy(
        self,
        policy_config: dict,
        episodes: int | None = None,
    ) -> EvaluationResult:
        """Run a policy for multiple episodes and return aggregated results.

        Default implementation loops over step(). Adapters may override
        for batch execution (e.g. Arena subprocess runner).
        """
        from rosclaw_darwin.evaluation.evaluator import Evaluator
        evaluator = Evaluator(self)
        return evaluator.evaluate_policy(policy_config, episodes=episodes)

    def close(self) -> None:
        """Clean up simulator resources."""

    @property
    def is_built(self) -> bool:
        return self._env is not None
