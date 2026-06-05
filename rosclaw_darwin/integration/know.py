"""KnowBridge: knowledge source for task generation hints."""

from __future__ import annotations

from typing import Any


class KnowBridge:
    """Provide long-horizon composition hints from task ontology."""

    def __init__(self):
        self._ontology: dict[str, Any] = {}

    def load_ontology(self, data: dict[str, Any]) -> None:
        self._ontology = data

    def get_composition_hints(self, task_name: str) -> list[str]:
        """Get suggested task compositions for a given task."""
        hints = self._ontology.get("compositions", {})
        return hints.get(task_name, [])

    def get_affordance_hints(self, affordance: str) -> list[str]:
        """Get tasks that use a given affordance."""
        tasks = self._ontology.get("affordance_tasks", {})
        return tasks.get(affordance, [])
