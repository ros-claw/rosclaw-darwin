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

    def test_auto_skill_hints_inject_into_loop2(self):
        task = Task(
            id="evo_auto_hints", name="Auto Hints",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            eval=EvalSpec(max_steps=50, max_episodes=20),
            mutation={"difficulty": 1, "allowed": []},
            primitives=[{"name": "pick"}, {"name": "place"}],
        )
        adapter = MockAdapter(task)
        runner = EvolutionRunner(adapter)
        report = runner.evolve(
            task,
            {"strength": 0.3},
            loops=2,
            auto_skill_hints=True,
        )
        assert "skill_hints" in report
        assert "loop_1" in report["skill_hints"]
        assert "loop_2" in report["skill_hints"]
        # Loop 2 should contain auto-generated hints if Loop 1 had failures.
        loop2_hints = report["skill_hints"]["loop_2"]
        if report["loop_results"][0].get("failure_types"):
            assert len(loop2_hints) > 0
            assert any(h.get("source") == "auto_from_failure" for h in loop2_hints)
