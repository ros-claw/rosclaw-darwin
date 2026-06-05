"""TaskLoader: load ROSClaw-TDL tasks from YAML/JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import Task


class TaskLoader:
    """Load and manage ROSClaw-TDL tasks."""

    def __init__(self, tasks_dir: str | None = None):
        self.tasks_dir = Path(tasks_dir) if tasks_dir else Path.cwd() / "configs" / "tasks"
        self._registry: dict[str, Task] = {}

    def load(self, source: str | Path | dict[str, Any]) -> Task:
        if isinstance(source, dict):
            return Task.from_dict(source)
        if isinstance(source, str):
            try:
                path_exists = Path(source).exists()
            except OSError:
                path_exists = False
            if not path_exists:
                # Treat as inline YAML/JSON content
                text = source
                if text.strip().startswith("{"):
                    return Task.from_dict(json.loads(text))
                return Task.from_yaml(text)
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            return Task.from_yaml(text)
        if path.suffix == ".json":
            return Task.from_dict(json.loads(text))
        return Task.from_yaml(text)

    def load_all(self, pattern: str = "*.yaml") -> list[Task]:
        tasks: list[Task] = []
        for path in self.tasks_dir.rglob(pattern):
            try:
                tasks.append(self.load(path))
            except Exception as exc:
                print(f"[TaskLoader] skip {path.name}: {exc}")
        return tasks

    def register(self, task: Task) -> None:
        self._registry[task.id] = task

    def get(self, task_id: str) -> Task | None:
        return self._registry.get(task_id)

    def list_tasks(self) -> list[str]:
        return list(self._registry.keys())
