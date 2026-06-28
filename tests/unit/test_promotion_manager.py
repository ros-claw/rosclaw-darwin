"""Tests for FailureToHint v3.4 evidence-aware promotion manager."""

from __future__ import annotations

from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.evolution.evidence_status import EvidenceStatus
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine
from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry
from rosclaw_darwin.evolution.promotion_manager import PromotionManager


def _make_summary(
    rescued: int = 0,
    newly_failed: int = 0,
    baseline_successes: int = 0,
    candidate_successes: int = 0,
    valid_pairs: int = 10,
    total_pairs: int = 10,
) -> PairedEvaluationSummary:
    return PairedEvaluationSummary(
        task_id="goal_pose_dex_cube_official",
        baseline_policy="v3",
        candidate_policy="candidate",
        seed_range="0:9",
        total_pairs=total_pairs,
        valid_pairs=valid_pairs,
        rescued_count=rescued,
        newly_failed_count=newly_failed,
        unchanged_success_count=baseline_successes - newly_failed,
        unchanged_failure_count=valid_pairs - candidate_successes - rescued,
        invalid_pair_count=total_pairs - valid_pairs,
        net_delta=rescued - newly_failed,
        baseline_success_rate=round(baseline_successes / valid_pairs, 4) if valid_pairs else 0.0,
        candidate_success_rate=round(candidate_successes / valid_pairs, 4) if valid_pairs else 0.0,
    )


def test_blocked_external_route_is_blocked():
    recipe = HintRecipe(
        name="large_yaw",
        source="auto_rule",
        trigger_tags=["large_yaw_torsional_slip"],
        hints=["diagnosis_only"],
        route_selection="blocked_external",
    )
    status = PromotionManager(None).evaluate(recipe)
    assert isinstance(status, EvidenceStatus)
    assert status.promotion_status == "blocked_external"
    assert status.evidence_gate_passed is False
    assert "outside" in status.gate_reason.lower()


def test_human_escalation_route_requires_review():
    recipe = HintRecipe(
        name="risky",
        source="manual",
        trigger_tags=["collision_risk"],
        hints=["human_escalation"],
        route_selection="human_escalation",
    )
    status = PromotionManager(None).evaluate(recipe)
    assert status.promotion_status == "human_escalation"
    assert status.evidence_gate_passed is False


def test_no_gate_keeps_experimental():
    recipe = HintRecipe(
        name="candidate",
        source="auto_rule",
        trigger_tags=["grip_force_insufficient"],
        hints=["lower_reclose"],
        route_selection="conditional_micro_recovery",
    )
    status = PromotionManager(None).evaluate(recipe)
    assert status.promotion_status == "experimental_only"
    assert status.evidence_gate_passed is False
    assert "No evidence_gate" in status.gate_reason


def test_unknown_gate_type_keeps_experimental():
    recipe = HintRecipe(
        name="candidate",
        source="auto_rule",
        trigger_tags=["tag"],
        hints=["hint"],
        route_selection="conditional_micro_recovery",
        evidence_gate={"gate_type": "unknown_gate"},
    )
    status = PromotionManager(None).evaluate(recipe)
    assert status.promotion_status == "experimental_only"
    assert "Unknown evidence_gate type" in status.gate_reason


def test_paired_gate_passes_and_promotes_candidate_recovery():
    summary = _make_summary(
        rescued=3,
        newly_failed=0,
        baseline_successes=8,
        candidate_successes=10,
        valid_pairs=10,
    )
    recipe = HintRecipe(
        name="seed24_recovery",
        source="auto_rule",
        trigger_tags=["grip_force_insufficient"],
        hints=["lower_reclose"],
        route_selection="conditional_micro_recovery",
        evidence_gate={
            "gate_type": "paired_no_regression",
            "min_rescued_count": 1,
            "max_newly_failed_count": 0,
            "min_candidate_success_rate": 0.9,
            "max_new_failure_rate": 0.05,
        },
    )
    status = PromotionManager(summary).evaluate(recipe)
    assert status.promotion_status == "candidate_recovery"
    assert status.evidence_gate_passed is True
    assert status.paired_summary is not None


def test_paired_gate_fails_due_to_newly_failed():
    summary = _make_summary(
        rescued=3,
        newly_failed=2,
        baseline_successes=8,
        candidate_successes=9,
        valid_pairs=10,
    )
    recipe = HintRecipe(
        name="seed24_recovery",
        source="auto_rule",
        trigger_tags=["grip_force_insufficient"],
        hints=["lower_reclose"],
        route_selection="conditional_micro_recovery",
        evidence_gate={
            "gate_type": "paired_no_regression",
            "min_rescued_count": 1,
            "max_newly_failed_count": 0,
        },
    )
    status = PromotionManager(summary).evaluate(recipe)
    assert status.promotion_status == "experimental_only"
    assert status.evidence_gate_passed is False
    assert "newly_failed_count=2" in status.gate_reason


def test_paired_gate_fails_when_summary_missing():
    recipe = HintRecipe(
        name="seed24_recovery",
        source="auto_rule",
        trigger_tags=["grip_force_insufficient"],
        hints=["lower_reclose"],
        route_selection="conditional_micro_recovery",
        evidence_gate={"gate_type": "paired_no_regression"},
    )
    status = PromotionManager(None).evaluate(recipe)
    assert status.promotion_status == "experimental_only"
    assert "requires a PairedEvaluationSummary" in status.gate_reason


def test_from_summary_dict_round_trip():
    summary = _make_summary(
        rescued=1,
        newly_failed=0,
        baseline_successes=9,
        candidate_successes=10,
        valid_pairs=10,
    )
    mgr = PromotionManager.from_summary_dict(summary.model_dump(mode="json"))
    assert mgr.paired_eval is not None
    assert mgr.paired_eval.rescued_count == 1


def test_evidence_status_json_round_trip():
    status = EvidenceStatus(
        recipe_name="r",
        route_selection="conditional_micro_recovery",
        promotion_status="candidate_recovery",
        evidence_gate_passed=True,
        gate_reason="passed",
        required_evidence={"gate_type": "paired_no_regression"},
    )
    data = status.to_dict()
    restored = EvidenceStatus.model_validate(data)
    assert restored.recipe_name == "r"
    assert restored.promotion_status == "candidate_recovery"
    assert restored.evidence_gate_passed is True


def test_large_yaw_recipe_with_gate_still_blocked():
    """A blocked_external route must not be promoted even if an evidence gate is declared."""
    summary = _make_summary(rescued=5, newly_failed=0, baseline_successes=5, candidate_successes=10)
    recipe = HintRecipe(
        name="large_yaw",
        source="auto_rule",
        trigger_tags=["large_yaw_torsional_slip"],
        hints=["diagnosis_only"],
        route_selection="blocked_external",
        evidence_gate={"gate_type": "paired_no_regression"},
    )
    status = PromotionManager(summary).evaluate(recipe)
    assert status.promotion_status == "blocked_external"
    assert status.evidence_gate_passed is False


def test_evaluate_recipe_evidence_returns_statuses():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="seed24_recovery",
                source="auto_rule",
                trigger_tags=["grip_force_insufficient", "low_object_z_at_grasp"],
                hints=["lower_reclose"],
                route_selection="conditional_micro_recovery",
                evidence_gate={
                    "gate_type": "paired_no_regression",
                    "min_rescued_count": 1,
                    "max_newly_failed_count": 0,
                },
            )
        ]
    )
    summary = _make_summary(rescued=2, newly_failed=0, baseline_successes=8, candidate_successes=10)
    engine = FailureToHintEngine(rules=[])
    signatures = [
        FailureSignature(
            task_id="goal_pose_dex_cube_official",
            episode_id=0,
            failure_type="grasp_failed",
            signature_tags=["grip_force_insufficient", "low_object_z_at_grasp"],
            hint_relevant_tags=["grip_force_insufficient"],
        )
    ]
    statuses = engine.evaluate_recipe_evidence(
        signatures, paired_summary=summary.model_dump(mode="json"), recipe_registry=registry
    )
    assert len(statuses) == 1
    assert statuses[0].promotion_status == "candidate_recovery"
    assert statuses[0].evidence_gate_passed is True


def test_suggest_from_signatures_attaches_evidence_status_when_summary_given():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="seed24_recovery",
                source="auto_rule",
                trigger_tags=["grip_force_insufficient", "low_object_z_at_grasp"],
                hints=["lower_reclose"],
                route_selection="conditional_micro_recovery",
                evidence_gate={
                    "gate_type": "paired_no_regression",
                    "min_rescued_count": 1,
                    "max_newly_failed_count": 0,
                },
            )
        ]
    )
    summary = _make_summary(rescued=2, newly_failed=0, baseline_successes=8, candidate_successes=10)
    engine = FailureToHintEngine(rules=[])
    signatures = [
        FailureSignature(
            task_id="goal_pose_dex_cube_official",
            episode_id=0,
            failure_type="grasp_failed",
            signature_tags=["grip_force_insufficient", "low_object_z_at_grasp"],
            hint_relevant_tags=["grip_force_insufficient"],
        )
    ]
    hints = engine.suggest_from_signatures(
        signatures,
        recipe_registry=registry,
        paired_summary=summary.model_dump(mode="json"),
    )
    assert len(hints) == 1
    assert hints[0].promotion_status == "candidate_recovery"
    assert hints[0].evidence_status is not None
    assert hints[0].evidence_status["evidence_gate_passed"] is True
