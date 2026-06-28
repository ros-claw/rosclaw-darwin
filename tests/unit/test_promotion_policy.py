"""Unit tests for PromotionPolicy."""

from __future__ import annotations

from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.registry import (
    PROMOTION_LEVELS,
    can_promote,
    evaluate_paired_no_regression,
    get_claims,
    promotion_level_from_summary,
)


def test_can_promote_same_status():
    assert can_promote("candidate_recovery", "candidate_recovery") is True


def test_blocked_external_cannot_be_promoted():
    for dest in PROMOTION_LEVELS:
        if dest != "blocked_external":
            assert can_promote("blocked_external", dest) is False


def test_diagnosis_only_cannot_skip_to_candidate():
    assert can_promote("diagnosis_only", "candidate_recovery") is False
    assert can_promote("diagnosis_only", "experimental_only") is True


def test_experimental_cannot_skip_to_validated():
    assert can_promote("experimental_only", "validated_recovery") is False
    assert can_promote("experimental_only", "candidate_recovery") is True


def test_evaluate_paired_no_regression_passes():
    summary = PairedEvaluationSummary(
        task_id="goal_pose_dex_cube_official",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:199",
        valid_pairs=100,
        baseline_success_rate=0.99,
        candidate_success_rate=0.99,
        rescued_count=2,
        newly_failed_count=0,
        baseline_failed_seeds=[24, 198],
        candidate_failed_seeds=[],
        rescued_seeds=[24, 198],
        newly_failed_seeds=[],
    )
    passed, passed_gates, failed_gates = evaluate_paired_no_regression(summary)
    assert passed is True
    assert "rescued_count" in passed_gates
    assert failed_gates == []


def test_evaluate_paired_no_regression_fails_when_newly_failed():
    summary = PairedEvaluationSummary(
        task_id="goal_pose_dex_cube_official",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:199",
        valid_pairs=100,
        baseline_success_rate=0.99,
        candidate_success_rate=0.99,
        rescued_count=2,
        newly_failed_count=1,
        baseline_failed_seeds=[24, 198],
        candidate_failed_seeds=[99],
        rescued_seeds=[24, 198],
        newly_failed_seeds=[99],
    )
    passed, _, failed_gates = evaluate_paired_no_regression(summary)
    assert passed is False
    assert any("newly_failed_count" in g for g in failed_gates)


def test_promotion_level_from_summary_candidate():
    summary = PairedEvaluationSummary(
        task_id="goal_pose_dex_cube_official",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:199",
        valid_pairs=100,
        baseline_success_rate=0.99,
        candidate_success_rate=0.99,
        rescued_count=2,
        newly_failed_count=0,
        baseline_failed_seeds=[24, 198],
        candidate_failed_seeds=[],
        rescued_seeds=[24, 198],
        newly_failed_seeds=[],
    )
    assert promotion_level_from_summary(summary) == "candidate_recovery"


def test_promotion_level_from_summary_experimental_when_no_rescue():
    summary = PairedEvaluationSummary(
        task_id="goal_pose_dex_cube_official",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:199",
        valid_pairs=100,
        baseline_success_rate=0.99,
        candidate_success_rate=0.99,
        rescued_count=0,
        newly_failed_count=0,
        baseline_failed_seeds=[],
        candidate_failed_seeds=[],
        rescued_seeds=[],
        newly_failed_seeds=[],
    )
    assert promotion_level_from_summary(summary) == "experimental_only"


def test_get_claims_blocked_external_disallowed():
    claims = get_claims("blocked_external")
    assert any("honestly block" in c for c in claims["allowed"])
    assert any("Darwin solved it" in c for c in claims["disallowed"])


def test_get_claims_candidate_recovery_disallows_transferable():
    claims = get_claims("candidate_recovery")
    assert any("transferable skill" in c for c in claims["disallowed"])
