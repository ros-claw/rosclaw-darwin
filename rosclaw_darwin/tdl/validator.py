"""TDL validator: ensure task definitions are well-formed."""

from __future__ import annotations

from typing import Any

from .schema import Task, TaskHorizon


class TaskValidator:
    """Validate ROSClaw-TDL tasks."""

    REQUIRED_PRIMITIVES = {"pick", "place", "grasp", "open", "close", "navigate_to", "press"}

    def validate(self, task: Task | dict[str, Any]) -> tuple[bool, list[str]]:
        if isinstance(task, dict):
            try:
                task = Task.model_validate(task)
            except Exception as exc:
                return False, [f"Schema validation failed: {exc}"]

        errors: list[str] = []

        if not task.id:
            errors.append("Task id is required")
        if not task.name:
            errors.append("Task name is required")
        if not task.scene:
            errors.append("Task scene is required")
        if not task.embodiment:
            errors.append("Task embodiment is required")
        if not task.embodiment.robot:
            errors.append("Task embodiment.robot is required")

        if task.eval.max_steps is not None and task.eval.max_steps <= 0:
            errors.append("eval.max_steps must be > 0")
        if task.eval.max_episodes is not None and task.eval.max_episodes <= 0:
            errors.append("eval.max_episodes must be > 0")

        # Check primitives have names
        for i, p in enumerate(task.primitives):
            if not p.name:
                errors.append(f"primitives[{i}].name is required")

        # Check objects have names
        seen_objects: set[str] = set()
        for i, o in enumerate(task.objects):
            if not o.name:
                errors.append(f"objects[{i}].name is required")
            if o.name in seen_objects:
                errors.append(f"Duplicate object name: {o.name}")
            seen_objects.add(o.name)

        # Validate horizon
        if isinstance(task.horizon, str) and task.horizon not in {h.value for h in TaskHorizon}:
            errors.append(f"Invalid horizon: {task.horizon}")

        return len(errors) == 0, errors

    def validate_file(self, path: str) -> tuple[bool, list[str]]:
        from pathlib import Path

        from .loader import TaskLoader
        loader = TaskLoader()
        try:
            task = loader.load(Path(path))
        except Exception as exc:
            return False, [f"Failed to load task: {exc}"]
        return self.validate(task)
