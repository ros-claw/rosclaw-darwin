"""Tests for task composer."""

import pytest

from rosclaw_darwin.evolution.composer import TaskComposer
from rosclaw_darwin.tdl.schema import EmbodimentSpec, Primitive, SceneSpec, Task, TaskHorizon


class TestTaskComposer:
    def test_compose_two_tasks(self):
        t1 = Task(
            id="t1", name="Open",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            primitives=[Primitive(name="open")],
        )
        t2 = Task(
            id="t2", name="Pick",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            primitives=[Primitive(name="grasp")],
        )
        composer = TaskComposer()
        composed = composer.compose([t1, t2])
        assert len(composed.primitives) == 2
        assert composed.horizon == TaskHorizon.composite
        assert t1.id in composed.parents
        assert t2.id in composed.parents

    def test_compose_empty_raises(self):
        composer = TaskComposer()
        with pytest.raises(ValueError):
            composer.compose([])
