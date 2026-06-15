"""Unit tests for ManualHintMiner."""

from __future__ import annotations

from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evolution.manual_hint_miner import (
    mine_candidate_rules,
    mine_candidate_rules_from_ablation,
)


def _sig(task_id: str, episode_id: int, tags: list[str], success: bool = False) -> FailureSignature:
    return FailureSignature(
        task_id=task_id,
        episode_id=episode_id,
        failure_type="target_not_reached_after_lift" if not success else "none",
        signature_tags=tags,
        success=success,
    )


def test_no_rule_when_no_improvement():
    baseline = [_sig("lift_object", i, ["final_alignment_gap"]) for i in range(5)]
    manual = [_sig("lift_object", i, ["final_alignment_gap"]) for i in range(5)]
    rules = mine_candidate_rules(
        task_id="lift_object",
        baseline_signatures=baseline,
        variant_signatures=manual,
        manual_hints=["target_tracking"],
        baseline_progress=0.5,
        variant_progress=0.5,
    )
    assert rules == []


def test_rule_mined_when_progress_improves():
    baseline = [_sig("lift_object", i, ["final_alignment_gap", "lifted_but_not_aligned"]) for i in range(5)]
    manual = [_sig("lift_object", i, ["final_alignment_gap"]) for i in range(4)] + [_sig("lift_object", 4, [], success=True)]
    rules = mine_candidate_rules(
        task_id="lift_object",
        baseline_signatures=baseline,
        variant_signatures=manual,
        manual_hints=["target_tracking", "precision_target_tracking"],
        baseline_progress=0.5,
        variant_progress=0.6,
    )
    assert len(rules) == 1
    rule = rules[0]
    assert rule.source == "mined_from_manual"
    assert rule.hint_level == "skill_candidate"
    assert "final_alignment_gap" in rule.trigger_tags
    assert "target_tracking" in rule.hints
    assert rule.confidence > 0.5


def test_ablation_wrapper_reports_comparison():
    baseline = [_sig("goal_pose", i, ["unstable_grasp"]) for i in range(5)]
    manual = [_sig("goal_pose", i, ["unstable_grasp"]) for i in range(3)] + [_sig("goal_pose", 3, [], success=True), _sig("goal_pose", 4, [], success=True)]
    auto = [_sig("goal_pose", i, ["unstable_grasp"]) for i in range(5)]
    result = mine_candidate_rules_from_ablation(
        task_id="goal_pose",
        baseline_signatures=baseline,
        manual_signatures=manual,
        auto_signatures=auto,
        manual_hints=["longer_gripper_close", "stabilize_lift"],
        baseline_progress=0.49,
        manual_progress=0.52,
        auto_progress=0.47,
        baseline_success_rate=0.0,
        manual_success_rate=0.4,
        auto_success_rate=0.0,
    )
    assert result["task_id"] == "goal_pose"
    assert len(result["candidate_rules"]) == 1
    assert result["comparison"]["manual_better_than_auto"] is True
