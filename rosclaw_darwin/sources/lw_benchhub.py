"""LW-BenchHub importer."""

from __future__ import annotations

from pathlib import Path

from rosclaw_darwin.sources.primitive_inference import enrich_objects, infer_primitives
from rosclaw_darwin.tdl.schema import (
    EmbodimentSpec,
    EvalSpec,
    ExecutionBackend,
    ExecutionMode,
    ExecutionSpec,
    ObjectSpec,
    ProvenanceSpec,
    SceneSpec,
    Task,
    TaskSource,
)

from .base import SourceImporter


class LWBenchHubImporter(SourceImporter):
    name = "lw_benchhub"

    def scan(self) -> list[dict]:
        if not self.repo_path:
            return []
        repo = Path(self.repo_path)
        records: list[dict] = []
        # Scan for task configs
        for cfg_dir in [repo / "configs", repo / "tasks"]:
            if cfg_dir.exists():
                for f in cfg_dir.rglob("*.yaml"):
                    try:
                        import yaml
                        data = yaml.safe_load(f.read_text())
                        if isinstance(data, dict) and (data.get("name") or data.get("task_name")):
                            data["_source_path"] = str(f.relative_to(repo))
                            records.append(data)
                    except Exception:
                        continue
        # Scan lw_benchhub_tasks python files for real task definitions
        tasks_dir = repo / "lw_benchhub_tasks"
        if tasks_dir.exists():
            for py_file in tasks_dir.rglob("*.py"):
                if py_file.name.startswith("_") or py_file.name == "base_task.py":
                    continue
                try:
                    text = py_file.read_text()
                    # Extract class names that look like tasks
                    import re
                    classes = re.findall(r"class\s+(\w+)\s*\(", text)
                    for cls_name in classes:
                        if cls_name.endswith("Base"):
                            continue
                        records.append({
                            "_type": "py_task",
                            "_source_path": str(py_file.relative_to(repo)),
                            "class_name": cls_name,
                            "name": cls_name,
                        })
                except Exception:
                    continue
        # Also scan python files for env registrations
        for py_file in repo.rglob("*.py"):
            try:
                text = py_file.read_text()
                if "gym.register" in text or "register(" in text:
                    records.append({
                        "_type": "py_registration",
                        "_source_path": str(py_file.relative_to(repo)),
                        "raw": text,
                    })
            except Exception:
                continue
        return records

    def import_task(self, record: dict) -> Task:
        if record.get("_type") == "py_registration":
            return self._import_from_py(record)
        return self._import_from_yaml(record)

    def _import_from_yaml(self, record: dict) -> Task:
        name = record.get("name", record.get("task_name", "unknown"))
        task_id = f"lw_{name.lower().replace(' ', '_')}"
        env_name = record.get("environment", name)
        embodiment = record.get("embodiment", "unitree_g1")
        objects = record.get("objects", [])
        description = record.get("description", "")
        objects = [
            ObjectSpec(name=o.get("name", f"obj_{i}"), category=o.get("type"))
            for i, o in enumerate(objects)
        ]
        objects = enrich_objects(objects)
        primitives = infer_primitives(
            name=name,
            description=description,
            success_conditions=record.get("success_conditions", []),
            objects=objects,
        )
        return Task(
            id=task_id,
            name=name,
            description=description,
            source=TaskSource.lw_benchhub,
            domain=record.get("domain", "manipulation"),
            horizon=record.get("horizon", "short"),
            scene=SceneSpec(
                name=record.get("scene", "default"),
                domain=record.get("scene_domain", "unknown"),
            ),
            embodiment=EmbodimentSpec(
                robot=embodiment,
                control_mode=record.get("control_mode"),
            ),
            objects=objects,
            primitives=primitives,
            eval=EvalSpec(
                max_steps=record.get("max_steps", 1000),
                max_episodes=record.get("max_episodes", 20),
            ),
            execution=ExecutionSpec(
                executable=True,
                backend=ExecutionBackend.arena,
                mode=ExecutionMode.docker,
                requires_gpu=True,
                requires_docker=True,
                native_env_name=env_name,
                adapter="arena",
            ),
            provenance=ProvenanceSpec(
                source=TaskSource.lw_benchhub,
                source_repo=str(self.repo_path) if self.repo_path else None,
                source_path=record.get("_source_path"),
                native_env_name=env_name,
                native_config={
                    "environment": env_name,
                    "embodiment": embodiment,
                },
            ),
        )

    def _import_from_py(self, record: dict) -> Task:
        # Fallback: create a minimal task from python registration
        path = record.get("_source_path", "unknown.py")
        class_name = record.get("class_name", Path(path).stem)
        name = class_name
        objects = [ObjectSpec(name="object", affordances=["graspable", "movable"])]
        objects = enrich_objects(objects)
        primitives = infer_primitives(name=name, objects=objects)
        return Task(
            id=f"lw_{name.lower()}",
            name=name,
            source=TaskSource.lw_benchhub,
            scene=SceneSpec(name="default"),
            embodiment=EmbodimentSpec(robot="unitree_g1"),
            objects=objects,
            primitives=primitives,
            execution=ExecutionSpec(
                executable=False,
                backend=ExecutionBackend.unknown,
                mode=ExecutionMode.unknown,
                reason="lw_py_fallback_no_native_env",
            ),
            provenance=ProvenanceSpec(
                source=TaskSource.lw_benchhub,
                source_repo=str(self.repo_path) if self.repo_path else None,
                source_path=path,
                native_env_name=class_name,
            ),
        )
