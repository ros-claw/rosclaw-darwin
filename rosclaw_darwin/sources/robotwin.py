"""RoboTwin importer."""

from __future__ import annotations

from pathlib import Path

from rosclaw_darwin.sources.primitive_inference import enrich_objects, infer_primitives
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, ObjectSpec, ProvenanceSpec, SceneSpec, Task, TaskSource

from .base import SourceImporter


class RoboTwinImporter(SourceImporter):
    name = "robotwin"

    def scan(self) -> list[dict]:
        if not self.repo_path:
            return []
        repo = Path(self.repo_path)
        records: list[dict] = []
        # Scan task_config YAMLs
        task_config_dir = repo / "task_config"
        if task_config_dir.exists():
            for f in task_config_dir.rglob("*.yml"):
                records.append({
                    "task_name": f.stem,
                    "config_path": str(f.relative_to(repo)),
                })
        # Scan description/task_instruction files
        desc_dir = repo / "description" / "task_instruction"
        if desc_dir.exists():
            for f in desc_dir.rglob("*.txt"):
                records.append({
                    "task_name": f.stem,
                    "instruction_path": str(f.relative_to(repo)),
                })
        # Fallback: data dirs
        data_dir = repo / "data"
        if data_dir.exists():
            for task_dir in data_dir.iterdir():
                if task_dir.is_dir():
                    records.append({
                        "task_name": task_dir.name,
                        "data_dir": str(task_dir),
                    })
        # Deduplicate by task_name
        seen = set()
        deduped = []
        for r in records:
            name = r["task_name"]
            if name not in seen:
                seen.add(name)
                deduped.append(r)
        return deduped

    def import_task(self, record: dict) -> Task:
        name = record["task_name"]
        task_id = f"robotwin_{name.lower().replace(' ', '_')}"
        data_dir = record.get("data_dir", "")
        objects = [ObjectSpec(name="object", affordances=["graspable", "movable"])]
        objects = enrich_objects(objects)
        primitives = infer_primitives(name=name, objects=objects)
        return Task(
            id=task_id,
            name=name.replace("_", " ").title(),
            source=TaskSource.robotwin,
            domain="bimanual_manipulation",
            horizon="short",
            scene=SceneSpec(name="workspace"),
            embodiment=EmbodimentSpec(robot="robotwin_default_bimanual"),
            objects=objects,
            primitives=primitives,
            eval=EvalSpec(max_steps=1000, max_episodes=20),
            provenance=ProvenanceSpec(
                source=TaskSource.robotwin,
                source_repo=str(self.repo_path) if self.repo_path else None,
                native_task_name=name,
                native_config={"data_dir": data_dir},
            ),
        )
