"""Tests for cross-task skill transfer via the persistent skill registry."""
from __future__ import annotations

from rosclaw_darwin.adapters.mock import MockAdapter
from rosclaw_darwin.evolution.runner import EvolutionRunner
from rosclaw_darwin.evolution.skill_registry import SkillRegistry
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, ObjectSpec, Primitive, SceneSpec, Task


def _make_task(task_id: str, primitive: str, affordance: str) -> Task:
    return Task(
        id=task_id,
        name=task_id,
        scene=SceneSpec(name="kitchen"),
        embodiment=EmbodimentSpec(robot="franka"),
        eval=EvalSpec(max_steps=50, max_episodes=10),
        objects=[ObjectSpec(name="obj", affordances=[affordance])],
        primitives=[Primitive(name=primitive)],
        mutation={"difficulty": 1, "seed": 42},
    )


def test_skill_hints_improve_mock_success_rate(tmp_path):
    """A skill discovered from one task should transfer to a similar second task."""
    registry_path = tmp_path / "skills.json"

    # Task A: pick an object -> should discover a pick skill.
    task_a = _make_task("task_a", "pick", "graspable")
    adapter_a = MockAdapter(task_a)
    runner_a = EvolutionRunner(
        adapter_a,
        config={"skill_discovery": {"path": str(registry_path), "min_task_count": 1}},
    )
    runner_a.evolve(task_a, {"strength": 0.3}, loops=1, episodes=10)
    assert runner_a.skill_registry.validated_count() >= 1

    # Task B: similar pick task; the registry should provide a pick skill hint.
    task_b = _make_task("task_b", "pick", "graspable")
    adapter_b = MockAdapter(task_b)
    runner_b = EvolutionRunner(
        adapter_b,
        config={"skill_discovery": {"path": str(registry_path), "min_task_count": 1}},
    )
    # Sanity: registry was loaded from disk.
    assert runner_b.skill_registry.validated_count() >= 1

    report_b = runner_b.evolve(task_b, {"strength": 0.3}, loops=1, episodes=10)
    loop_b = report_b["loop_results"][0]
    # The mock adapter reports the effective success probability; skill hints
    # should raise it above the baseline (0.2 for strength=0.3, difficulty=1).
    success_prob_b = loop_b.get("metadata", {}).get("success_prob", 0.0)
    assert success_prob_b > 0.2


def test_registry_query_matches_task_affordances():
    registry = SkillRegistry(config={"min_task_count": 1})
    task = Task(
        id="t",
        name="T",
        scene=SceneSpec(name="kitchen"),
        embodiment=EmbodimentSpec(robot="franka"),
        eval=EvalSpec(max_steps=50, max_episodes=5),
        objects=[ObjectSpec(name="door", affordances=["openable"])],
        primitives=[Primitive(name="open")],
    )
    skills = registry.extract_from_task(task)
    for s in skills:
        s.evidence = {"success_gain": 0.2}
        registry.add(s)

    matched = registry.query_for_task(task)
    assert any(s.name == "open" for s in matched)
