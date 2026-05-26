"""IsaacLab-Arena environment adapter.

Wraps Arena's composable Scene + Embodiment + Task primitives.
When IsaacLab-Arena is not installed, falls back to a mock mode for
unit tests and development.
"""

from __future__ import annotations

from typing import Any

from rosclaw_darwin.tdl.schema import Task
from .base import BaseEnvironmentAdapter


class ArenaAdapter(BaseEnvironmentAdapter):
    """Adapter for NVIDIA IsaacLab-Arena simulator."""

    name = "isaaclab-arena"

    def __init__(self, task: Task, robot: str = "franka", headless: bool = True, **kwargs: Any):
        super().__init__(task, **kwargs)
        self.robot = robot
        self.headless = headless
        self._arena_available = self._check_arena()
        self._step_count = 0

    @staticmethod
    def _check_arena() -> bool:
        try:
            import isaaclab_arena  # noqa: F401
            return True
        except ImportError:
            return False

    def build(self) -> None:
        if self._arena_available:
            self._build_real()
        else:
            self._build_mock()

    def _build_real(self) -> None:
        """Build using real IsaacLab-Arena APIs."""
        # Deferred import so the module loads even without isaaclab_arena installed.
        from isaaclab_arena import ArenaEnvBuilder  # type: ignore[import-untyped]

        builder = ArenaEnvBuilder()
        builder.set_scene(self.task.scene)
        builder.set_embodiment(self.robot)

        # Map ROSClaw primitives to Arena task objectives
        for p in self.task.primitives:
            builder.add_task_objective(p.name, target=p.target, params=p.params)

        self._env = builder.make_registered(headless=self.headless)

    def _build_mock(self) -> None:
        """Mock environment for development without Isaac Sim."""
        self._env = _MockArenaEnv(self.task)

    def reset(self) -> dict[str, Any]:
        if self._env is None:
            raise RuntimeError("Environment not built. Call build() first.")
        self._step_count = 0
        return self._env.reset()

    def step(self, action: dict[str, Any]) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        if self._env is None:
            raise RuntimeError("Environment not built. Call build() first.")
        self._step_count += 1
        return self._env.step(action)

    def close(self) -> None:
        if self._env is not None:
            if hasattr(self._env, "close"):
                self._env.close()
            self._env = None

    def get_state(self) -> dict[str, Any]:
        return {
            **super().get_state(),
            "backend": "isaaclab-arena" if self._arena_available else "mock",
            "robot": self.robot,
            "step_count": self._step_count,
        }


class _MockArenaEnv:
    """Minimal mock that satisfies the gym-like interface for unit tests."""

    def __init__(self, task: Task):
        self.task = task
        self._step = 0
        self._max_steps = task.eval_config.max_steps

    def reset(self) -> dict[str, Any]:
        self._step = 0
        return {"observation": "mock_reset", "task_id": self.task.id}

    def step(self, action: dict[str, Any]) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        self._step += 1
        terminated = self._step >= self._max_steps
        reward = 1.0 if terminated else 0.0
        info = {"step": self._step, "mock": True}
        obs = {"observation": f"mock_step_{self._step}", "action": action}
        return obs, reward, terminated, info

    def close(self) -> None:
        pass
