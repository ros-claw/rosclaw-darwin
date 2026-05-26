"""Tests for TDL schema and loader."""

import pytest
from rosclaw_darwin.tdl.schema import Task, Primitive, Object, Constraint, EvalConfig
from rosclaw_darwin.tdl.loader import TaskLoader


class TestTaskSchema:
    def test_task_creation(self):
        task = Task(
            id="test_001",
            name="Test Task",
            primitives=[Primitive(name="Pick", target="cup")],
            objects=[Object(name="cup", object_type="graspable")],
        )
        assert task.id == "test_001"
        assert task.primitives[0].name == "Pick"

    def test_task_to_yaml_roundtrip(self):
        task = Task(
            id="test_yaml",
            name="YAML Test",
            primitives=[Primitive(name="Place")],
        )
        yaml_text = task.to_yaml()
        restored = Task.from_yaml(yaml_text)
        assert restored.id == task.id
        assert restored.primitives[0].name == "Place"


class TestTaskLoader:
    def test_load_from_dict(self):
        loader = TaskLoader()
        data = {
            "id": "dict_task",
            "name": "Dict Task",
            "primitives": [{"name": "Open", "target": "door"}],
        }
        task = loader.load(data)
        assert task.id == "dict_task"
        assert task.primitives[0].target == "door"

    def test_register_and_get(self):
        loader = TaskLoader()
        task = Task(id="reg_001", name="Registered")
        loader.register(task)
        assert loader.get("reg_001") is not None
        assert loader.list_tasks() == ["reg_001"]

    def test_parse_bddl(self):
        loader = TaskLoader()
        bddl_text = "(:goal (and (ontop ?milk.n.01_1 ?counter.n.01_1) (open ?fridge.n.01_1)))"
        task = loader._parse_bddl(bddl_text, "test_bddl")
        assert task.id == "bddl_test_bddl"
        assert any(p.name == "Place" for p in task.primitives)
        assert any(p.name == "Open" for p in task.primitives)
