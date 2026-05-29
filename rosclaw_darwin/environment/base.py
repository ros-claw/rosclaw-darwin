"""Base environment adapter interface.

All simulator backends (IsaacLab-Arena, MuJoCo, PyBullet, Habitat) implement
this interface so Darwin can swap backends without changing evaluation logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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
    def reset(self) -> dict[str, Any]:
        """Reset the environment; return initial observation."""

    @abstractmethod
    def step(self, action: Any) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        """Execute one action.

        Args:
            action: Raw action from policy (dict, tensor, or array).

        Returns:
            observation, reward, terminated, truncated, info
        """

    @abstractmethod
    def close(self) -> None:
        """Clean up simulator resources."""

    @property
    def is_built(self) -> bool:
        return self._env is not None

    def get_state(self) -> dict[str, Any]:
        """Return current environment state snapshot."""
        return {"task_id": self.task.id, "built": self.is_built}
