"""Tests for task mutators."""

from rosclaw_darwin.evolution.mutators import (
    MUTATOR_REGISTRY,
    ConstraintMutator,
    DistractorMutator,
    ObjectMutator,
    SpatialMutator,
)
from rosclaw_darwin.tdl.schema import EmbodimentSpec, ObjectSpec, SceneSpec, Task


class TestMutators:
    def test_spatial_mutator_changes_position(self):
        task = Task(
            id="base", name="Base",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            objects=[ObjectSpec(name="cup")],
        )
        mut = SpatialMutator()
        t2 = mut.mutate(task, seed=1)
        assert t2.objects[0].metadata.get("position") is not None

    def test_object_mutator_swaps(self):
        task = Task(
            id="base", name="Base",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            objects=[ObjectSpec(name="milk")],
        )
        mut = ObjectMutator()
        t2 = mut.mutate(task, seed=1)
        assert t2.objects[0].name != "milk"

    def test_distractor_mutator_adds_objects(self):
        task = Task(
            id="base", name="Base",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            objects=[ObjectSpec(name="cup")],
        )
        mut = DistractorMutator()
        t2 = mut.mutate(task, seed=1)
        assert len(t2.objects) > len(task.objects)

    def test_constraint_mutator_adds_constraint(self):
        task = Task(
            id="base", name="Base",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            constraints=["collision_free"],
        )
        mut = ConstraintMutator()
        t2 = mut.mutate(task, seed=1)
        assert len(t2.constraints) >= len(task.constraints)

    def test_all_mutators_registered(self):
        assert "spatial" in MUTATOR_REGISTRY
        assert "object" in MUTATOR_REGISTRY
        assert "distractor" in MUTATOR_REGISTRY
