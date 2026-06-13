"""Tests for TDL schema."""

from rosclaw_darwin.tdl.fingerprints import task_fingerprint
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.tdl.schema import EmbodimentSpec, ObjectSpec, Primitive, SceneSpec, Task
from rosclaw_darwin.tdl.validator import TaskValidator


class TestTaskSchema:
    def test_task_creation(self):
        task = Task(
            id="test_001",
            name="Test Task",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="unitree_g1"),
            primitives=[Primitive(name="grasp", args={"target": "cup"})],
            objects=[ObjectSpec(name="cup", category="graspable")],
        )
        assert task.id == "test_001"
        assert task.primitives[0].name == "grasp"

    def test_task_to_yaml_roundtrip(self):
        task = Task(
            id="test_yaml",
            name="YAML Test",
            scene=SceneSpec(name="table"),
            embodiment=EmbodimentSpec(robot="franka"),
            primitives=[Primitive(name="place")],
        )
        yaml_text = task.to_yaml()
        restored = Task.from_yaml(yaml_text)
        assert restored.id == task.id
        assert restored.primitives[0].name == "place"


class TestTaskLoader:
    def test_load_from_dict(self):
        loader = TaskLoader()
        data = {
            "id": "dict_task",
            "name": "Dict Task",
            "scene": {"name": "kitchen"},
            "embodiment": {"robot": "franka"},
            "primitives": [{"name": "open", "args": {"target": "door"}}],
        }
        task = loader.load(data)
        assert task.id == "dict_task"
        assert task.primitives[0].args["target"] == "door"


class TestTaskValidator:
    def test_valid_task(self):
        task = Task(
            id="valid",
            name="Valid",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
        )
        ok, errors = TaskValidator().validate(task)
        assert ok
        assert not errors

    def test_invalid_missing_robot(self):
        task = Task(
            id="invalid",
            name="Invalid",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot=""),
        )
        ok, errors = TaskValidator().validate(task)
        assert not ok
        assert any("robot" in e.lower() for e in errors)


class TestFingerprints:
    def test_fingerprint_stable(self):
        task = Task(
            id="fp_test",
            name="FP Test",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            primitives=[Primitive(name="grasp")],
            objects=[ObjectSpec(name="cup", affordances=["graspable"])],
        )
        fp1 = task_fingerprint(task)
        fp2 = task_fingerprint(task)
        assert fp1 == fp2
