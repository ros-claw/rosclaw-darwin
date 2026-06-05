"""BEHAVIOR-1K semantic importer."""

from __future__ import annotations

from pathlib import Path

from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, ObjectSpec, ProvenanceSpec, SceneSpec, Task, TaskSource

from .base import SourceImporter


class Behavior1KImporter(SourceImporter):
    name = "behavior1k"

    def scan(self) -> list[dict]:
        if not self.repo_path:
            return []
        repo = Path(self.repo_path)
        records: list[dict] = []
        # Scan for BDDL files
        for bddl_file in repo.rglob("*.bddl"):
            try:
                text = bddl_file.read_text()
                # Build unique name from parent dir + stem
                activity_name = bddl_file.parent.name
                unique_name = f"{activity_name}_{bddl_file.stem}"
                records.append({
                    "_type": "bddl",
                    "_source_path": str(bddl_file.relative_to(repo)),
                    "name": unique_name,
                    "raw": text,
                })
            except Exception:
                continue
        # Scan for activity definitions
        for act_file in repo.rglob("activity_*"):
            if act_file.is_dir():
                for sub in act_file.iterdir():
                    if sub.suffix in (".json", ".yaml", ".yml"):
                        try:
                            import yaml
                            data = yaml.safe_load(sub.read_text()) if sub.suffix in (".yaml", ".yml") else {}
                            if isinstance(data, dict):
                                data["_type"] = "activity"
                                data["_source_path"] = str(sub.relative_to(repo))
                                records.append(data)
                        except Exception:
                            continue
        return records

    def import_task(self, record: dict) -> Task:
        if record.get("_type") == "bddl":
            return self._import_from_bddl(record)
        return self._import_from_activity(record)

    def _import_from_bddl(self, record: dict) -> Task:
        text = record.get("raw", "")
        name = record.get("name", "unknown")
        task_id = f"behavior1k_{name.lower().replace(' ', '_')}"

        # Extract goal conditions
        success_conditions: list[str] = []
        objects: list[ObjectSpec] = []

        for line in text.splitlines():
            line = line.strip()
            if line.startswith(";") or not line:
                continue
            # Extract predicates
            if line.startswith("(") and "?" in line:
                tokens = line.strip("()").split()
                if tokens:
                    pred = tokens[0]
                    if pred in ("ontop", "inside", "nextto", "on", "open", "close"):
                        success_conditions.append(line.strip("()"))
                    # Extract objects
                    for tok in tokens:
                        if tok.startswith("?"):
                            obj_name = tok.lstrip("?").split(".")[0]
                            if not any(o.name == obj_name for o in objects):
                                objects.append(ObjectSpec(name=obj_name))

        return Task(
            id=task_id,
            name=name.replace("_", " ").title(),
            source=TaskSource.behavior1k,
            domain="household",
            horizon="long",
            scene=SceneSpec(name="household", domain="household"),
            embodiment=EmbodimentSpec(robot="unitree_g1"),
            objects=objects,
            eval=EvalSpec(success_conditions=success_conditions),
            provenance=ProvenanceSpec(
                source=TaskSource.behavior1k,
                source_repo=str(self.repo_path) if self.repo_path else None,
                source_path=record.get("_source_path"),
            ),
            metadata={"executable": False, "semantic_only": True},
        )

    def _import_from_activity(self, record: dict) -> Task:
        name = record.get("activity_name", record.get("name", "unknown"))
        task_id = f"behavior1k_{name.lower().replace(' ', '_')}"
        objects = record.get("objects", [])
        return Task(
            id=task_id,
            name=name,
            source=TaskSource.behavior1k,
            domain="household",
            horizon="long",
            scene=SceneSpec(name=record.get("scene", "household"), domain="household"),
            embodiment=EmbodimentSpec(robot="unitree_g1"),
            objects=[ObjectSpec(name=o.get("name", f"obj_{i}")) for i, o in enumerate(objects)],
            eval=EvalSpec(success_conditions=record.get("goal_conditions", [])),
            provenance=ProvenanceSpec(
                source=TaskSource.behavior1k,
                source_repo=str(self.repo_path) if self.repo_path else None,
                source_path=record.get("_source_path"),
            ),
            metadata={"executable": False, "semantic_only": True},
        )
