"""TDL exporter: serialize tasks to various formats."""

from __future__ import annotations

import json
from pathlib import Path

from .schema import Task


class TaskExporter:
    """Export ROSClaw-TDL tasks to files."""

    @staticmethod
    def to_yaml(task: Task, path: str | Path | None = None) -> str:
        text = task.to_yaml()
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return text

    @staticmethod
    def to_json(task: Task, path: str | Path | None = None) -> str:
        text = json.dumps(task.model_dump(mode="json"), indent=2, ensure_ascii=False)
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return text

    @staticmethod
    def export_batch(tasks: list[Task], out_dir: str | Path, fmt: str = "yaml") -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for task in tasks:
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in task.id)
            if fmt == "yaml":
                path = out_dir / f"{safe_name}.yaml"
                TaskExporter.to_yaml(task, path)
            else:
                path = out_dir / f"{safe_name}.json"
                TaskExporter.to_json(task, path)
            paths.append(path)
        return paths
