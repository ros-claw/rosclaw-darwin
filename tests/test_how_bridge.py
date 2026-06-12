"""Tests for HowBridge skill extraction."""

from rosclaw_darwin.integration.how import FAILURE_SKILL_TEMPLATES, HowBridge


def _make_experience(task_id: str = "t1", success_rate: float = 0.0, failure_types: dict | None = None) -> dict:
    return {
        "task_id": task_id,
        "run_id": "run_1",
        "adapter": "mock",
        "metrics": {"success_rate": success_rate, "progress_mean": success_rate},
        "failure_types": failure_types or {},
    }


class TestHowBridge:
    def test_empty_experiences(self):
        bridge = HowBridge()
        assert bridge.extract_skills([]) == []

    def test_grasp_failure_generates_grasp_adjust_skill(self):
        bridge = HowBridge()
        exp = _make_experience(success_rate=0.0, failure_types={"grasp_failed": 3})
        candidates = bridge.extract_skills([exp])
        assert any(c.name == "grasp_adjust" for c in candidates)
        grasp = next(c for c in candidates if c.name == "grasp_adjust")
        assert "graspable" in grasp.affordances
        assert grasp.evidence["target_failure_type"] == "grasp_failed"
        assert "close_gripper" in grasp.action_pattern

    def test_collision_failure_generates_collision_avoidance_skill(self):
        bridge = HowBridge()
        exp = _make_experience(success_rate=0.2, failure_types={"collision": 2})
        candidates = bridge.extract_skills([exp])
        assert any(c.name == "collision_avoidance" for c in candidates)

    def test_unknown_failure_falls_back_to_adaptive_retry(self):
        bridge = HowBridge()
        exp = _make_experience(success_rate=0.0, failure_types={"weird_failure": 1})
        candidates = bridge.extract_skills([exp])
        assert any(c.name == "adaptive_retry" for c in candidates)

    def test_success_improvement_adds_adaptive_skill(self):
        bridge = HowBridge()
        exp1 = _make_experience(success_rate=0.1, failure_types={"timeout": 1})
        exp2 = _make_experience(success_rate=0.6, failure_types={"timeout": 1})
        candidates = bridge.extract_skills([exp1, exp2])
        assert any(c.name == "adaptive_skill" for c in candidates)
        adaptive = next(c for c in candidates if c.name == "adaptive_skill")
        assert adaptive.evidence["success_gain"] == 0.5

    def test_multiple_failure_types_yield_distinct_candidates(self):
        bridge = HowBridge()
        exp = _make_experience(
            success_rate=0.0,
            failure_types={"grasp_failed": 2, "collision": 1},
        )
        candidates = bridge.extract_skills([exp])
        names = {c.name for c in candidates}
        assert "grasp_adjust" in names
        assert "collision_avoidance" in names
        assert len(candidates) == len({c.fingerprint for c in candidates})

    def test_failure_skill_templates_cover_known_types(self):
        known = {"grasp_failed", "handle_grasp_failed", "object_dropped", "collision", "timeout",
                 "door_not_opened", "object_not_found", "navigation_failed", "planning_failed",
                 "policy_crash", "robot_fallen", "unknown"}
        assert known.issubset(FAILURE_SKILL_TEMPLATES.keys())
