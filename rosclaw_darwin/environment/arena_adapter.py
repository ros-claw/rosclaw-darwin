"""IsaacLab-Arena environment adapter.

Wraps Arena's composable Scene + Embodiment + Task primitives.
When IsaacLab-Arena is not installed, falls back to a mock mode for
unit tests and development.
"""

from __future__ import annotations

from typing import Any, Callable

from rosclaw_darwin.tdl.schema import Task
from .base import BaseEnvironmentAdapter


class ArenaAdapter(BaseEnvironmentAdapter):
    """Adapter for NVIDIA IsaacLab-Arena simulator.

    Supports three modes:
      1. **mock** (default): No GPU required, for development/CI.
      2. **real**: Direct import in a Kit-enabled Python process.
      3. **docker**: Runs inside Docker container with full Isaac Sim.

    The mode is auto-selected based on availability:
      - If `isaaclab_arena` is importable -> real mode.
      - If `SIMULATION_APP` env var is set -> docker mode.
      - Otherwise -> mock mode.
    """

    name = "isaaclab-arena"

    def __init__(
        self,
        task: Task,
        robot: str = "franka",
        headless: bool = True,
        mode: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(task, **kwargs)
        self.robot = robot
        self.headless = headless
        self._mode = mode or self._detect_mode()
        self._step_count = 0
        self._simulation_app: Any | None = None

    @staticmethod
    def _detect_mode() -> str:
        import os

        # Docker mode: explicit override via env var
        if os.environ.get("ROSCLAW_ARENA_MODE") == "docker":
            return "docker"

        # Real mode: isaaclab_arena is importable (must be in Kit process)
        try:
            import isaaclab_arena  # noqa: F401
            return "real"
        except ImportError:
            pass

        # Mock mode: fallback for development
        return "mock"

    def build(self) -> None:
        if self._mode == "real":
            self._build_real()
        elif self._mode == "docker":
            self._build_docker()
        else:
            self._build_mock()

    def _build_real(self) -> None:
        """Build using real IsaacLab-Arena APIs.

        Requires running inside an Omniverse Kit process (e.g. via
        `/isaac-sim/kit/kit`).
        """
        from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

        builder = ArenaEnvBuilder()
        builder.set_scene(self.task.scene)
        builder.set_embodiment(self.robot)

        for p in self.task.primitives:
            builder.add_task_objective(p.name, target=p.target, params=p.params)

        self._env = builder.make_registered(headless=self.headless)

    def _build_docker(self) -> None:
        """Build inside Docker container with Isaac Sim.

        This mode starts the Omniverse Kit automatically, then creates the
        Arena environment within the running Kit process.
        """
        # Isaac Sim 6.0 uses isaacsim.simulation_app instead of omni.isaac.kit
        if self._simulation_app is None:
            try:
                from isaacsim.simulation_app import SimulationApp

                self._simulation_app = SimulationApp(
                    {"headless": self.headless, "width": 1280, "height": 720}
                )
            except ImportError as e:
                raise RuntimeError(
                    "IsaacSim SimulationApp not available. "
                    "Ensure the container is based on nvcr.io/nvidia/isaac-sim."
                ) from e

        # Now build the Arena environment
        self._build_real()

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
        if self._simulation_app is not None:
            self._simulation_app.close()
            self._simulation_app = None

    def get_state(self) -> dict[str, Any]:
        return {
            **super().get_state(),
            "backend": self._mode,
            "robot": self.robot,
            "step_count": self._step_count,
        }

    @classmethod
    def create_in_container(
        cls,
        task: Task,
        container_name: str = "rosclaw_darwin",
        **kwargs: Any,
    ) -> "ArenaAdapter":
        """Create an adapter that runs inside a Docker container.

        This is the recommended way to use real Isaac Sim from host Python.
        """
        import os

        os.environ["ROSCLAW_ARENA_MODE"] = "docker"
        return cls(task, **kwargs)


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
