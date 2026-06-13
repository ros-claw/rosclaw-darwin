"""Match ROSClaw tasks to Arena environments using the capability registry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from rosclaw_darwin.tdl.schema import Task

from .capability_registry import ArenaCapabilityRegistry


class MatchResult(BaseModel):
    env_name: str
    native_env_name: str
    score: float
    matched_primitives: list[str]
    missing_required_primitives: list[str]
    matched_objects: list[str]
    missing_required_objects: list[str]
    matched_scene: bool
    matched_robot: bool
    warnings: list[str] = []
    executable: bool = False


class TaskArenaMatcher:
    """Score-based matcher between a ROSClaw Task and Arena environments."""

    # Weighting for scoring components.
    _SCENE_WEIGHT = 0.25
    _PRIMITIVE_WEIGHT = 0.35
    _OBJECT_WEIGHT = 0.15
    _ROBOT_WEIGHT = 0.15
    _HORIZON_WEIGHT = 0.10

    def __init__(self, registry: ArenaCapabilityRegistry | None = None):
        self.registry = registry or ArenaCapabilityRegistry.load()

    def match(self, task: Task) -> list[MatchResult]:
        """Return all environment matches sorted by descending score."""
        task_primitives = {p.name.lower() for p in task.primitives}
        task_objects = {self.registry.map_object(o.name).lower() for o in task.objects}
        task_robot = task.embodiment.robot.lower()
        task_scene = (task.scene.name or task.scene.domain or "default").lower()
        task_horizon = str(task.horizon).lower()

        results: list[MatchResult] = []
        for env_name, caps in self.registry.data.get("environments", {}).items():
            env_primitives = {p.lower() for p in caps.get("supported_primitives", [])}
            env_required = {p.lower() for p in caps.get("required_primitives", [])}
            env_objects = {o.lower() for o in caps.get("supported_objects", [])}
            env_required_objects = {o.lower() for o in caps.get("required_objects", [])}
            env_robots = {r.lower() for r in caps.get("supported_robots", [])}
            env_scenes = {s.lower() for s in caps.get("scene_domains", [])}
            env_horizon = str(caps.get("horizon", "")).lower()

            matched_primitives = sorted(task_primitives & env_primitives)
            missing_required = sorted(env_required - task_primitives)
            matched_objects = sorted(task_objects & env_objects)
            missing_required_objects = sorted(env_required_objects - task_objects)
            matched_scene = task_scene in env_scenes
            matched_robot = task_robot in env_robots
            matched_horizon = task_horizon == env_horizon if env_horizon else True

            warnings: list[str] = []
            if missing_required:
                warnings.append(f"Missing required primitives: {', '.join(missing_required)}")
            if missing_required_objects:
                warnings.append(f"Missing required objects: {', '.join(missing_required_objects)}")
            if not matched_robot:
                warnings.append(f"Robot '{task.embodiment.robot}' not in supported robots")
            if not matched_scene:
                warnings.append(f"Scene '{task.scene.name or task.scene.domain}' not in supported scene domains")

            # Hard gate: if a required primitive is missing, the task cannot run in this env.
            if missing_required:
                score = 0.0
                executable = False
            else:
                score = 0.0
                if env_primitives:
                    score += self._PRIMITIVE_WEIGHT * (len(matched_primitives) / len(env_primitives))
                if matched_scene:
                    score += self._SCENE_WEIGHT
                if matched_robot:
                    score += self._ROBOT_WEIGHT
                if env_objects:
                    score += self._OBJECT_WEIGHT * (len(matched_objects) / len(env_objects))
                if env_horizon and matched_horizon:
                    score += self._HORIZON_WEIGHT
                executable = score > 0.0

            results.append(
                MatchResult(
                    env_name=env_name,
                    native_env_name=caps.get("native_env_name", env_name),
                    score=round(score, 3),
                    matched_primitives=matched_primitives,
                    missing_required_primitives=missing_required,
                    matched_objects=matched_objects,
                    missing_required_objects=missing_required_objects,
                    matched_scene=matched_scene,
                    matched_robot=matched_robot,
                    warnings=warnings,
                    executable=executable,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)

        # Fallback: exact match by provenance or metadata native_env_name.
        if not results or not results[0].executable:
            native_env = None
            if task.provenance and task.provenance.native_env_name:
                native_env = task.provenance.native_env_name
            if not native_env and task.metadata.get("arena_env_args"):
                native_env = task.metadata["arena_env_args"].get("environment")
            if native_env:
                for env_name, caps in self.registry.data.get("environments", {}).items():
                    if caps.get("native_env_name") == native_env:
                        results.insert(
                            0,
                            MatchResult(
                                env_name=env_name,
                                native_env_name=native_env,
                                score=1.0,
                                matched_primitives=[],
                                missing_required_primitives=[],
                                matched_objects=[],
                                missing_required_objects=[],
                                matched_scene=True,
                                matched_robot=True,
                                warnings=["matched by native_env_name fallback"],
                                executable=True,
                            ),
                        )
                        break

        return results

    def best_match(self, task: Task, threshold: float = 0.5) -> MatchResult | None:
        """Return the highest-scoring match if it meets the threshold."""
        matches = self.match(task)
        if not matches:
            return None
        best = matches[0]
        if best.score < threshold:
            return None
        return best

    def can_execute(self, task: Task) -> bool:
        """Return True if the task can be mapped to a known executable Arena environment."""
        best = self.best_match(task)
        return best is not None and best.executable

    def build_arena_args(self, task: Task) -> dict[str, Any] | None:
        """Build the environment args dict expected by ArenaAdapter."""
        best = self.best_match(task)
        if best is None:
            return None
        caps = self.registry.get(best.env_name)
        supported_objects = {o.lower() for o in caps.get("supported_objects", [])}
        supported_mapped = {self.registry.map_object(o).lower() for o in supported_objects}

        # Pick the first task object whose mapped name is supported, else first supported object.
        mapped_obj = None
        for obj in task.objects:
            mapped = self.registry.map_object(obj.name).lower()
            if mapped in supported_mapped:
                mapped_obj = mapped
                break
        if mapped_obj is None:
            # Preserve registry order rather than alphabetical order.
            for obj_name in caps.get("supported_objects", ["dex_cube"]):
                mapped = self.registry.map_object(obj_name).lower()
                if mapped:
                    mapped_obj = mapped
                    break
            if mapped_obj is None:
                mapped_obj = "dex_cube"

        return {
            "environment": best.native_env_name,
            "object": mapped_obj,
            "embodiment": self.registry.map_robot(task.embodiment.robot),
        }
