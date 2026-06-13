"""Tests for MockAdapter."""

from rosclaw_darwin.adapters.mock import MockAdapter
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, SceneSpec, Task


class TestMockAdapter:
    def test_build_and_reset(self):
        task = Task(
            id="mock_test", name="Mock",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            eval=EvalSpec(max_steps=100, max_episodes=10),
        )
        adapter = MockAdapter(task)
        adapter.build()
        obs = adapter.reset()
        assert obs["task_id"] == "mock_test"

    def test_run_policy(self):
        task = Task(
            id="mock_test", name="Mock",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            eval=EvalSpec(max_steps=100, max_episodes=10),
            mutation={"difficulty": 1, "allowed": []},
        )
        adapter = MockAdapter(task)
        result = adapter.run_policy({"strength": 0.8}, episodes=20)
        assert result.task_id == "mock_test"
        assert "success_rate" in result.metrics
        assert result.metrics["num_episodes"] == 20
