"""Tests for failure-to-hint engine."""

from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine
from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry


class TestFailureToHint:
    def test_grasp_failed_generates_grasp_adjust(self):
        engine = FailureToHintEngine.from_yaml()
        hints = engine.suggest({"grasp_failed": 3})
        names = [h.name for h in hints]
        assert "grasp_adjust" in names
        assert any(h.source_failure_type == "grasp_failed" for h in hints)

    def test_no_failures_returns_empty(self):
        engine = FailureToHintEngine.from_yaml()
        assert engine.suggest({}) == []
        assert engine.suggest({"grasp_failed": 0}) == []

    def test_unknown_failure_returns_empty(self):
        engine = FailureToHintEngine.from_yaml()
        assert engine.suggest({"unknown_failure": 5}) == []

    def test_deduplication(self):
        engine = FailureToHintEngine.from_yaml()
        hints = engine.suggest({"grasp_failed": 1, "object_not_lifted": 1})
        names = [h.name for h in hints]
        # longer_gripper_close appears in both rules but should only appear once.
        assert names.count("longer_gripper_close") == 1

    def test_from_result(self):
        engine = FailureToHintEngine.from_yaml()
        result = EvaluationResult(
            run_id="r1",
            task_id="t1",
            policy_id="p1",
            adapter="mock",
            status="completed",
            failure_types={"timeout": 2},
        )
        hints = engine.suggest_from_result(result)
        assert any(h.name == "efficient_execution" for h in hints)

    def test_from_signatures_uses_recipe_tags(self):
        registry = HintRecipeRegistry(
            recipes=[
                HintRecipe(
                    name="rotation_induced_slip_recipe",
                    source="auto_rule",
                    trigger_tags=["rotation_induced_slip"],
                    hints=["incremental_yaw_reorientation", "stabilize_after_rotation"],
                    parameter_overrides={"yaw_step_size": 0.10, "stabilize_steps_after_yaw": 20},
                    confidence=0.6,
                )
            ]
        )
        engine = FailureToHintEngine.from_yaml()
        signatures = [
            FailureSignature(
                task_id="goal_pose",
                episode_id=0,
                failure_type="target_not_reached_after_lift",
                signature_tags=["rotation_induced_slip", "lifted_then_dropped"],
                hint_relevant_tags=["rotation_induced_slip"],
            )
        ]
        hints = engine.suggest_from_signatures(signatures, recipe_registry=registry)
        names = [h.name for h in hints]
        assert "incremental_yaw_reorientation" in names
        assert "stabilize_after_rotation" in names
        assert all(h.source == "auto_from_signature_v3" for h in hints)
        assert any(h.parameter_overrides.get("yaw_step_size") == 0.10 for h in hints)

    def test_from_signatures_includes_source_recipe(self):
        registry = HintRecipeRegistry(
            recipes=[
                HintRecipe(
                    name="blocked_gripper_normal_recipe",
                    source="auto_rule",
                    trigger_tags=["blocked_gripper_normal"],
                    hints=["use_object_following_grasp_metric"],
                    parameter_overrides={"gripper_close_threshold": 0.03},
                    confidence=0.85,
                )
            ]
        )
        engine = FailureToHintEngine.from_yaml()
        signatures = [
            FailureSignature(
                task_id="goal_pose",
                episode_id=0,
                failure_type="grasp_failed",
                signature_tags=["blocked_gripper_normal"],
                hint_relevant_tags=["blocked_gripper_normal"],
            )
        ]
        hints = engine.suggest_from_signatures(signatures, recipe_registry=registry)
        assert any(h.source_recipe == "blocked_gripper_normal_recipe" for h in hints)

    def test_from_signatures_fallback_to_failure_type(self):
        engine = FailureToHintEngine.from_yaml()
        signatures = [
            FailureSignature(
                task_id="lift_object",
                episode_id=0,
                failure_type="grasp_failed",
                signature_tags=[],
                hint_relevant_tags=[],
            )
        ]
        hints = engine.suggest_from_signatures(signatures)
        names = [h.name for h in hints]
        assert "grasp_adjust" in names
        assert all(h.source == "auto_from_failure" for h in hints)
