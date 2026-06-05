"""DarwinExternalEnvironment for Arena Mode B integration."""

from __future__ import annotations

from typing import Any


class DarwinExternalEnvironment:
    """Placeholder for ROSClaw Native tasks in Arena.

    Inherits from Arena's external environment interface when available.
    """

    name = "darwin_external"

    def __init__(self, task_config: dict[str, Any]):
        self.task_config = task_config

    def reset(self) -> dict[str, Any]:
        return {"obs": "external_obs", "task": self.task_config}

    def step(self, action: Any) -> tuple[dict, float, bool, dict]:
        return {"obs": "external_obs"}, 0.0, False, {}
