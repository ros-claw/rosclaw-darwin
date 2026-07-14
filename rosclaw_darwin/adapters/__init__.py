"""ROSClaw-Darwin environment adapters."""

from __future__ import annotations

from rosclaw_darwin.adapters.base import BaseEnvironmentAdapter
from rosclaw_darwin.tdl.schema import Task


def get_adapter(name: str, task: Task, **kwargs: object) -> BaseEnvironmentAdapter:
    """Return an environment adapter by name.

    Supported adapters:
      - ``mock``: synthetic adapter for tests/CI.
      - ``arena``: IsaacLab-Arena Docker/subprocess adapter.
      - ``libero``: native LIBERO Gymnasium adapter.
    """
    if name == "mock":
        from rosclaw_darwin.adapters.mock import MockAdapter

        return MockAdapter(task, **kwargs)
    if name == "arena":
        from rosclaw_darwin.adapters.arena import ArenaAdapter

        return ArenaAdapter(task, **kwargs)
    if name == "libero":
        from rosclaw_darwin.adapters.libero import LiberoAdapter

        return LiberoAdapter(task, **kwargs)
    if name == "arena_official":
        from rosclaw_darwin.adapters.arena_official_runner_adapter import ArenaOfficialRunnerAdapter

        return ArenaOfficialRunnerAdapter(task=task, **kwargs)
    raise ValueError(f"Unknown adapter: {name!r}")


__all__ = ["BaseEnvironmentAdapter", "get_adapter"]
