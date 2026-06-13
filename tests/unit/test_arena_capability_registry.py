"""Tests for Arena capability registry and task matcher."""

from rosclaw_darwin.arena_bridge.capability_registry import ArenaCapabilityRegistry
from rosclaw_darwin.arena_bridge.task_matcher import TaskArenaMatcher
from rosclaw_darwin.tdl.schema import EmbodimentSpec, ObjectSpec, Primitive, SceneSpec, Task


class TestArenaCapabilityRegistry:
    def test_load_default_registry(self):
        registry = ArenaCapabilityRegistry.load()
        envs = registry.list_environments()
        assert "lift_object" in envs
        assert "kitchen_pick_and_place" in envs
        assert "franka_put_and_close_door" in envs

    def test_get_env(self):
        registry = ArenaCapabilityRegistry.load()
        lift = registry.get("lift_object")
        assert lift["backend"] == "arena"
        assert "pick" in lift["supported_primitives"]

    def test_object_mapping(self):
        registry = ArenaCapabilityRegistry.load()
        assert registry.map_object("cube") == "dex_cube"
        assert registry.map_object("milk_carton") == "milk_carton_hot3d_robolab"


class TestTaskArenaMatcher:
    def _task(self, **kwargs) -> Task:
        defaults = {
            "id": "test",
            "name": "Test",
            "scene": SceneSpec(name="table"),
            "embodiment": EmbodimentSpec(robot="franka"),
        }
        defaults.update(kwargs)
        return Task(**defaults)

    def test_lift_object_match(self):
        task = self._task(
            scene=SceneSpec(name="table"),
            objects=[ObjectSpec(name="cube")],
            primitives=[Primitive(name="pick"), Primitive(name="lift")],
        )
        matcher = TaskArenaMatcher()
        best = matcher.best_match(task)
        assert best is not None
        assert best.env_name == "lift_object"
        assert best.score > 0.5

    def test_kitchen_pick_place_match(self):
        task = self._task(
            scene=SceneSpec(name="kitchen"),
            objects=[ObjectSpec(name="cube")],
            primitives=[Primitive(name="pick"), Primitive(name="place")],
        )
        matcher = TaskArenaMatcher()
        best = matcher.best_match(task)
        assert best is not None
        assert best.env_name == "kitchen_pick_and_place"

    def test_put_and_close_door_match(self):
        task = self._task(
            scene=SceneSpec(name="kitchen"),
            objects=[ObjectSpec(name="cube"), ObjectSpec(name="microwave")],
            primitives=[Primitive(name="pick"), Primitive(name="place"), Primitive(name="close")],
        )
        matcher = TaskArenaMatcher()
        best = matcher.best_match(task)
        assert best is not None
        assert best.env_name == "franka_put_and_close_door"

    def test_missing_required_primitive_returns_zero_score(self):
        task = self._task(
            scene=SceneSpec(name="kitchen"),
            primitives=[Primitive(name="close")],
        )
        matcher = TaskArenaMatcher()
        matches = matcher.match(task)
        put_close = next((m for m in matches if m.env_name == "franka_put_and_close_door"), None)
        assert put_close is not None
        assert put_close.score == 0.0
        assert "place" in put_close.missing_required_primitives

    def test_build_arena_args(self):
        task = self._task(
            scene=SceneSpec(name="table"),
            objects=[ObjectSpec(name="cube")],
            primitives=[Primitive(name="pick"), Primitive(name="lift")],
        )
        matcher = TaskArenaMatcher()
        args = matcher.build_arena_args(task)
        assert args is not None
        assert args["environment"] == "lift_object"
        assert args["object"] == "dex_cube"
        assert args["embodiment"] == "franka_ik"

    def test_unknown_primitives_no_match(self):
        task = self._task(
            scene=SceneSpec(name="table"),
            primitives=[Primitive(name="navigate"), Primitive(name="wave")],
        )
        matcher = TaskArenaMatcher()
        best = matcher.best_match(task)
        assert best is None
