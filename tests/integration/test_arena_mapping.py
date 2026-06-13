"""Tests for ArenaAdapter primitive-to-environment mapping."""
from __future__ import annotations

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, ObjectSpec, SceneSpec, Task, TaskSource


def _task_with_primitives(name: str, primitives: list[tuple[str, dict]], objects: list[str] | None = None) -> Task:
    return Task(
        id=name,
        name=name,
        source=TaskSource.behavior1k,
        scene=SceneSpec(name="default"),
        embodiment=EmbodimentSpec(robot="franka"),
        objects=[ObjectSpec(name=o) for o in (objects or [])],
        primitives=[{"name": p, "args": a} for p, a in primitives],
        eval=EvalSpec(max_steps=100, max_episodes=1),
    )


def test_lift_primitive_maps_to_lift_object() -> None:
    task = _task_with_primitives("lift_cube", [("Lift", {})], objects=["cube"])
    adapter = ArenaAdapter(task, mode="mock")
    args = adapter._map_primitives_to_arena_env(task)
    assert args["environment"] == "lift_object"
    assert args["object"] == "dex_cube"


def test_pick_place_primitive_maps_to_kitchen_pick_and_place() -> None:
    task = _task_with_primitives("pick_place_bowl", [("Pick", {"target": "bowl"}), ("Place", {"target": "bowl"})], objects=["bowl"])
    adapter = ArenaAdapter(task, mode="mock")
    args = adapter._map_primitives_to_arena_env(task)
    assert args["environment"] == "kitchen_pick_and_place"
    assert args["object"] == "bowl_ycb_robolab"


def test_kitchen_pick_place_maps_to_kitchen_env() -> None:
    task = _task_with_primitives(
        "kitchen_pick_mug",
        [("Pick", {"target": "mug"}), ("Place", {"target": "sink"})],
        objects=["mug"],
    )
    task.scene.name = "kitchen"
    adapter = ArenaAdapter(task, mode="mock")
    args = adapter._map_primitives_to_arena_env(task)
    assert args["environment"] == "kitchen_pick_and_place"
    assert args["object"] == "mug"


def test_kitchen_place_close_maps_to_put_and_close_door() -> None:
    task = _task_with_primitives(
        "kitchen_put_close_microwave",
        [("Pick", {}), ("Place", {}), ("Close", {})],
        objects=["cube", "microwave"],
    )
    task.scene.name = "kitchen"
    adapter = ArenaAdapter(task, mode="mock")
    args = adapter._map_primitives_to_arena_env(task)
    assert args["environment"] == "franka_put_and_close_door"
    assert args["object"] == "dex_cube"
    assert args["embodiment"] == "franka_ik"


def test_unknown_object_falls_back_to_dex_cube() -> None:
    task = _task_with_primitives("pick_knife", [("Pick", {"target": "knife"})], objects=["knife"])
    adapter = ArenaAdapter(task, mode="mock")
    args = adapter._map_primitives_to_arena_env(task)
    assert args["environment"] == "lift_object"
    assert args["object"] == "dex_cube"


def test_sort_primitive_maps_to_tabletop_sort() -> None:
    task = _task_with_primitives("sort_cubes", [("Sort", {})], objects=["cube", "bin"])
    adapter = ArenaAdapter(task, mode="mock")
    args = adapter._map_primitives_to_arena_env(task)
    assert args["environment"] == "tabletop_sort_cubes"
