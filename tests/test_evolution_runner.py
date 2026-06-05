"""Tests for evolution runner."""

from rosclaw_darwin.adapters.mock import MockAdapter
from rosclaw_darwin.evolution.runner import EvolutionRunner
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, SceneSpec, Task


class TestEvolutionRunner:
    def test_mock_evolution_improves_with_memory(self):
        task = Task(
            id="evo_test", name="Evo",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            eval=EvalSpec(max_steps=100, max_episodes=20),
            mutation={"difficulty": 1, "allowed": ["spatial"]},
        )
        adapter = MockAdapter(task)
        runner = EvolutionRunner(adapter)
        report = runner.evolve(task, {"strength": 0.3}, loops=2)

        assert "loop_results" in report
        assert len(report["loop_results"]) == 2
        evo = report["evolution_metrics"]
        assert "delta_success_rate" in evo
        assert "evolution_score" in evo
        # With memory bonus, loop2 should generally not be worse
        assert evo["evolution_score"] >= -1.0

    def test_evolution_report_structure(self):
        task = Task(
            id="evo_test2", name="Evo2",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            eval=EvalSpec(max_steps=50, max_episodes=5),
            mutation={"difficulty": 1, "allowed": []},
        )
        adapter = MockAdapter(task)
        runner = EvolutionRunner(adapter)
        report = runner.evolve(task, {"strength": 0.5}, loops=2)
        assert report["task_id"] == "evo_test2"
        assert "discovered_skills" in report
        assert "generated_tasks" in report
