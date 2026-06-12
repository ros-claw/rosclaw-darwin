"""TaskLoader: load ROSClaw-TDL tasks from YAML/JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import rosclaw_darwin

from .schema import Task

# Package installation root (the directory that contains the rosclaw_darwin package).
# Used as a fallback when a relative task path cannot be resolved from CWD.
_PACKAGE_ROOT = Path(rosclaw_darwin.__file__).parent.parent


class TaskLoader:
    """Load and manage ROSClaw-TDL tasks."""

    def __init__(self, tasks_dir: str | None = None):
        self.tasks_dir = Path(tasks_dir) if tasks_dir else Path.cwd() / "configs" / "tasks"
        self._registry: dict[str, Task] = {}

    def _resolve_path(self, source: str) -> Path:
        """Resolve a path-like source against CWD, then package root."""
        path = Path(source)
        if path.is_absolute():
            return path
        # Try relative to current working directory first.
        cwd_path = Path.cwd() / path
        if cwd_path.exists():
            return cwd_path
        # Fallback to package root so CLI commands work from any directory.
        pkg_path = _PACKAGE_ROOT / path
        if pkg_path.exists():
            return pkg_path
        # Return the CWD-relative path so the caller raises a clear FileNotFoundError.
        return cwd_path

    def load(self, source: str | Path | dict[str, Any]) -> Task:
        if isinstance(source, dict):
            return Task.from_dict(source)
        # Resolve path-like sources against CWD, then package root.
        if isinstance(source, str):
            try:
                path = self._resolve_path(source)
            except OSError:
                path = Path(source)
        else:
            path = Path(source)
            if not path.is_absolute() and not path.exists():
                pkg_path = _PACKAGE_ROOT / path
                if pkg_path.exists():
                    path = pkg_path
        if not path.exists():
            # Treat string source as inline YAML/JSON content
            if isinstance(source, str):
                text = source
                if text.strip().startswith("{"):
                    return Task.from_dict(json.loads(text))
                return Task.from_yaml(text)
            raise FileNotFoundError(path)
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
