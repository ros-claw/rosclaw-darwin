"""TaskLoader: unify tasks from multiple benchmark sources into ROSClaw-TDL."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .schema import Task, Primitive, Object, Constraint, EvalConfig


class TaskLoader:
    """Load and normalize tasks from heterogeneous sources.

    Supported sources:
      - rosclaw-tdl   : native YAML / dict
      - bddl          : BEHAVIOR-1K BDDL definitions
      - robocasa      : RoboCasa task configs
      - libero        : LIBERO task JSON
      - arena         : IsaacLab-Arena environment configs
    """

    def __init__(self, tasks_dir: str | None = None):
        self.tasks_dir = Path(tasks_dir) if tasks_dir else Path(os.getcwd()) / "configs" / "tasks"
        self._registry: dict[str, Task] = {}

    def load(self, source: str | Path, fmt: str | None = None) -> Task:
        """Load a single task from file or dict.

        Args:
            source: File path, or dict for in-memory tasks.
            fmt:    Explicit format hint ("yaml", "json", "bddl", "robocasa",
                    "libero", "arena"). Auto-detected from extension if None.
        """
        if isinstance(source, dict):
            return Task.from_dict(source)

        path = Path(source)
        fmt = fmt or self._detect_format(path)
        text = path.read_text(encoding="utf-8")

        if fmt in ("yaml", "yml"):
            return Task.from_yaml(text)

        if fmt == "json":
            data = json.loads(text)
            return Task.from_dict(data)

        if fmt == "bddl":
            return self._parse_bddl(text, path.stem)

        if fmt == "robocasa":
            data = yaml.safe_load(text)
            return self._parse_robocasa(data, path.stem)

        if fmt == "libero":
            data = json.loads(text)
            return self._parse_libero(data, path.stem)

        if fmt == "arena":
            data = yaml.safe_load(text)
            return self._parse_arena(data, path.stem)

        raise ValueError(f"Unsupported task format: {fmt}")

    def load_all(self, pattern: str = "*.yaml") -> list[Task]:
        """Load all tasks matching glob pattern from tasks_dir."""
        tasks: list[Task] = []
        for path in self.tasks_dir.glob(pattern):
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

    # ------------------------------------------------------------------
    # Format-specific parsers (best-effort normalisation)
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_format(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in (".yaml", ".yml"):
            return "yaml"
        if ext == ".json":
            return "json"
        if ext == ".bddl":
            return "bddl"
        return "yaml"

    @staticmethod
    def _parse_bddl(text: str, name: str) -> Task:
        """Parse BEHAVIOR-1K BDDL into ROSClaw-TDL.

        BDDL syntax example:
            (:goal
                (and
                    (ontop ?milk.n.01_1 ?counter.n.01_1)
                    (inside ?fridge.n.01_1 ?kitchen.n.01_1)
                )
            )
        """
        primitives: list[Primitive] = []
        objects: list[Object] = []

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            # Extract predicates as primitives
            if line.startswith("(") and not line.startswith("(:goal"):
                tokens = line.strip("()").split()
                if tokens:
                    pred = tokens[0]
                    if pred in ("ontop", "inside", "nextto", "on"):
                        primitives.append(
                            Primitive(name="Place", target=tokens[1] if len(tokens) > 1 else None)
                        )
                    elif pred in ("open", "close"):
                        primitives.append(
                            Primitive(name=pred.capitalize(), target=tokens[1] if len(tokens) > 1 else None)
                        )

            # Extract object mentions (?object.n.01_1)
            import re

            for match in re.finditer(r"\?(\w+\.n\.\d+_\d+)", line):
                obj_name = match.group(1)
                if not any(o.name == obj_name for o in objects):
                    objects.append(Object(name=obj_name, object_type="generic"))

        return Task(
            id=f"bddl_{name}",
            name=name,
            source="bddl",
            description=f"Parsed from BEHAVIOR-1K BDDL: {name}",
            primitives=primitives,
            objects=objects,
        )

    @staticmethod
    def _parse_robocasa(data: dict[str, Any], name: str) -> Task:
        """Normalise a RoboCasa task config into ROSClaw-TDL."""
        primitives = [
            Primitive(name=p.get("type", "Unknown"), params=p)
            for p in data.get("atomic_actions", [])
        ]
        objects = [
            Object(name=o.get("name", f"obj_{i}"), object_type=o.get("type", "generic"))
            for i, o in enumerate(data.get("objects", []))
        ]
        return Task(
            id=f"robocasa_{name}",
            name=data.get("task_name", name),
            source="robocasa",
            scene=data.get("kitchen", "default"),
            primitives=primitives,
            objects=objects,
            eval_config=EvalConfig(
                max_steps=data.get("max_steps", 1000),
            ),
        )

    @staticmethod
    def _parse_libero(data: dict[str, Any], name: str) -> Task:
        """Normalise a LIBERO task JSON into ROSClaw-TDL."""
        return Task(
            id=f"libero_{name}",
            name=data.get("task", name),
            source="libero",
            scene=data.get("scene", "default"),
            primitives=[Primitive(name=p) for p in data.get("language", "").split()],
            objects=[Object(name=o) for o in data.get("objects", [])],
        )

    @staticmethod
    def _parse_arena(data: dict[str, Any], name: str) -> Task:
        """Normalise an IsaacLab-Arena config into ROSClaw-TDL."""
        scene = data.get("scene", {}).get("id", "default")
        task_cfg = data.get("task", {})
        primitives = [
            Primitive(name=a.get("type", "Unknown"))
            for a in task_cfg.get("actions", [])
        ]
        return Task(
            id=f"arena_{name}",
            name=task_cfg.get("name", name),
            source="arena",
            scene=scene,
            primitives=primitives,
            eval_config=EvalConfig(
                max_steps=task_cfg.get("max_steps", 1000),
            ),
        )
