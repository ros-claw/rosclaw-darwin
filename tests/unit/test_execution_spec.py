"""Tests for ExecutionSpec and result interpretation semantics."""

from rosclaw_darwin.tdl.schema import (
    EmbodimentSpec,
    ExecutionBackend,
    ExecutionMode,
    ExecutionSpec,
    SceneSpec,
    Task,
)


class TestExecutionSpec:
    def test_default_execution_spec(self):
        task = Task(
            id="exec_default",
            name="Default Execution",
            scene=SceneSpec(name="table"),
            embodiment=EmbodimentSpec(robot="franka"),
        )
        assert task.execution.executable is False
        assert task.execution.backend == ExecutionBackend.unknown
        assert task.execution.mode == ExecutionMode.unknown
        assert task.execution.semantic_only is False

    def test_execution_spec_roundtrip(self):
        task = Task(
            id="exec_roundtrip",
            name="Execution Roundtrip",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            execution=ExecutionSpec(
                executable=True,
                backend=ExecutionBackend.arena,
                mode=ExecutionMode.docker,
                requires_gpu=True,
                requires_docker=True,
                adapter="arena",
            ),
        )
        yaml_text = task.to_yaml()
        restored = Task.from_yaml(yaml_text)
        assert restored.execution.executable is True
        assert restored.execution.backend == ExecutionBackend.arena
        assert restored.execution.mode == ExecutionMode.docker
        assert restored.execution.requires_gpu is True

    def test_mock_result_cannot_claim_capability(self):
        result_meta = {
            "metric_scope": "mock_ci",
            "can_claim_capability": False,
            "claim_level": "infrastructure",
        }
        assert result_meta["can_claim_capability"] is False
        assert result_meta["claim_level"] == "infrastructure"

    def test_semantic_only_result_cannot_claim_execution(self):
        result_meta = {
            "metric_scope": "semantic_only",
            "can_claim_capability": False,
            "claim_level": "infrastructure",
        }
        assert result_meta["can_claim_capability"] is False

    def test_arena_real_result_can_claim_execution(self):
        result_meta = {
            "metric_scope": "arena_real",
            "can_claim_capability": True,
            "claim_level": "execution",
        }
        assert result_meta["can_claim_capability"] is True
        assert result_meta["claim_level"] == "execution"

    def test_arena_ablation_result_can_claim_evolution(self):
        result_meta = {
            "metric_scope": "arena_real",
            "can_claim_capability": True,
            "claim_level": "evolution",
        }
        assert result_meta["can_claim_capability"] is True
        assert result_meta["claim_level"] == "evolution"
