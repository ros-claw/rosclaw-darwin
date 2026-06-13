"""Tests for MemoryBridge."""

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.integration.memory import MemoryBridge
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, SceneSpec, Task


def _make_task(task_id: str = "t1") -> Task:
    return Task(
        id=task_id,
        name="Test Task",
        description="A test task.",
        scene=SceneSpec(name="kitchen"),
        embodiment=EmbodimentSpec(robot="franka"),
        eval=EvalSpec(max_steps=10, max_episodes=5),
    )


def _make_result(run_id: str, success_rate: float = 0.0) -> EvaluationResult:
    return EvaluationResult(
        run_id=run_id,
        task_id="t1",
        policy_id="zero",
        adapter="mock",
        status="completed",
        metrics={"success_rate": success_rate, "num_episodes": 5},
        failure_types={"miss": 1} if success_rate < 0.5 else {},
    )


class TestMemoryBridge:
    def test_record_and_query(self, tmp_path):
        bridge = MemoryBridge(mode="file", path=str(tmp_path / "global.jsonl"))
        task = _make_task()
        result = _make_result("run_1", success_rate=0.2)
        bridge.record_experience(task, result, evolution_run_id="evo_1")
        assert bridge.count() == 1
        experiences = bridge.query_experiences(task)
        assert len(experiences) == 1
        assert experiences[0]["evolution_run_id"] == "evo_1"
        assert experiences[0]["task_text"] == "A test task."

    def test_finalize_writes_per_run_store(self, tmp_path):
        bridge = MemoryBridge(mode="file", path=str(tmp_path / "global.jsonl"))
        task = _make_task()
        bridge.record_experience(task, _make_result("run_a", 0.2), evolution_run_id="evo_x")
        bridge.record_experience(task, _make_result("run_b", 0.8), evolution_run_id="evo_x")
        run_dir = tmp_path / "evo_x"
        bridge.finalize(run_dir)
        run_file = run_dir / "memory" / "experiences.jsonl"
        assert run_file.exists()
        lines = [line for line in run_file.read_text().splitlines() if line.strip()]
        assert len(lines) == 2

    def test_similar_experiences(self, tmp_path):
        bridge = MemoryBridge(mode="vector", path=str(tmp_path / "vec.jsonl"), embedding_model="keyword")
        task = _make_task("pick_red_cube")
        task.description = "pick the red cube"
        bridge.record_experience(task, _make_result("r1", 0.2), evolution_run_id="evo_1")
        task2 = _make_task("place_blue_cup")
        task2.description = "place the blue cup"
        bridge.record_experience(task2, _make_result("r2", 0.3), evolution_run_id="evo_1")
        similar = bridge.query_similar_experiences("pick red cube", top_k=2)
        assert similar[0]["task_id"] == "pick_red_cube"
