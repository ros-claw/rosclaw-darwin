"""Tests for skill registry."""

from rosclaw_darwin.evolution.skill_registry import SkillCandidate, SkillRegistry
from rosclaw_darwin.tdl.schema import EmbodimentSpec, ObjectSpec, Primitive, SceneSpec, Task


class TestSkillRegistry:
    def test_new_skill_requires_novelty_reuse_effectiveness(self):
        registry = SkillRegistry(config={"min_task_count": 2, "min_success_gain": 0.10})

        # Random action pattern should not count
        random_skill = SkillCandidate(
            id="random_1", name="random",
            action_pattern=["move"], affordances=[],
            source_task_ids=["task_1"],
            evidence={"success_gain": 0.05},
            fingerprint="fp_random",
        )
        assert not registry.is_valid_new_skill(random_skill)

        # Effective pattern with reuse should count
        good_skill = SkillCandidate(
            id="open_1", name="open",
            action_pattern=["grasp(handle)", "pull", "object_state_open"],
            affordances=["openable"],
            source_task_ids=["task_1", "task_2"],
            evidence={"success_gain": 0.15},
            fingerprint="fp_open",
        )
        assert registry.is_valid_new_skill(good_skill)
        assert registry.add(good_skill)
        assert registry.exists("fp_open")

    def test_persistence_round_trip(self, tmp_path):
        path = tmp_path / "skills.json"
        registry = SkillRegistry(config={"path": str(path), "min_task_count": 1})
        skill = SkillCandidate(
            id="pick_1", name="pick",
            action_pattern=["approach", "grasp", "lift"],
            affordances=["graspable"],
            source_task_ids=["task_1"],
            evidence={"success_gain": 0.2},
            fingerprint="fp_pick",
        )
        registry.add(skill)

        registry2 = SkillRegistry(config={"path": str(path), "min_task_count": 1})
        assert registry2.exists("fp_pick")
        assert registry2.query_for_task(
            Task(
                id="t", name="T",
                scene=SceneSpec(name="kitchen"),
                embodiment=EmbodimentSpec(robot="franka"),
                primitives=[Primitive(name="pick")],
                objects=[ObjectSpec(name="cube", affordances=["graspable"])],
            )
        )

    def test_extract_from_task(self):
        task = Task(
            id="task_open", name="Open",
            scene=SceneSpec(name="kitchen"),
            embodiment=EmbodimentSpec(robot="franka"),
            primitives=[Primitive(name="open"), Primitive(name="grasp")],
            objects=[ObjectSpec(name="fridge", affordances=["openable"])],
        )
        registry = SkillRegistry()
        candidates = registry.extract_from_task(task)
        assert len(candidates) > 0
        names = [c.name for c in candidates]
        assert "open" in names or "pick" in names
