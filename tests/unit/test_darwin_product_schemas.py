"""Unit tests for Darwin v1.0 schema surface."""

from __future__ import annotations

from rosclaw_darwin import schemas
from rosclaw_darwin.evaluation.object_validity import ObjectValidityReport
from rosclaw_darwin.evolution.evidence_status import EvidenceStatus


def test_task_validity_defaults():
    validity = schemas.TaskValidity(
        task_id="goal_pose_dex_cube_official",
        benchmark_scope="official_arena_asset",
        official_asset=True,
    )
    assert validity.validity_status == "valid"
    assert validity.can_claim_official_benchmark is False
    validity.can_claim_official_benchmark = (
        validity.official_asset and validity.validity_status == "valid"
    )
    assert validity.can_claim_official_benchmark is True


def test_task_validity_invalid_environment():
    obj = ObjectValidityReport(
        task_id="goal_pose_procedural_cube_fallback",
        collision_enabled=False,
        bbox_extent=[0.0, 0.0, 0.0],
    )
    obj = schemas.check_object_validity(obj)
    validity = schemas.TaskValidity(
        task_id="goal_pose_procedural_cube_fallback",
        benchmark_scope="invalid_environment",
        validity_status="invalid",
        object_validity=obj,
        reason=["collision_disabled", "invalid_bbox"],
    )
    assert validity.can_claim_ood_diagnostic is False
    assert not obj.valid


def test_failure_signal():
    signal = schemas.FailureSignal(name="slip_score", value=0.85, threshold=0.5)
    assert signal.name == "slip_score"
    assert signal.value == 0.85


def test_candidate_intervention():
    candidate = schemas.CandidateIntervention(
        name="seed24_micro_recovery",
        intervention_type="recovery",
        trigger_signals=["post_lift_slip"],
        action_type="parameter_override",
        status="candidate_recovery",
    )
    assert candidate.name == "seed24_micro_recovery"
    assert candidate.status == "candidate_recovery"


def test_paired_evidence_reexport():
    outcome = schemas.PairedSeedOutcome(
        seed=24,
        baseline_success=False,
        candidate_success=True,
        baseline_artifact_dir="baseline/seed_024",
        candidate_artifact_dir="candidate/seed_024",
    )
    assert outcome.delta_class == "rescued"


def test_promotion_decision():
    fth = EvidenceStatus(
        recipe_name="seed24_micro_recovery",
        route_selection="apply_recovery",
        promotion_status="candidate_recovery",
        evidence_gate_passed=True,
        gate_reason="rescued 2 seeds, newly_failed 0",
    )
    decision = schemas.PromotionDecision(
        candidate_name="seed24_micro_recovery",
        status="candidate_recovery",
        claim_level="candidate_recovery",
        passed_gates=["paired_no_regression", "rescued_count_positive"],
        failed_gates=[],
        allowed_claims=["no-regression candidate on evaluated seed set"],
        disallowed_claims=["validated_transferable_skill"],
        fth_status=fth,
    )
    d = decision.to_dict()
    assert d["status"] == "candidate_recovery"
    assert d["claim_level"] == "candidate_recovery"


def test_evidence_card():
    decision = schemas.PromotionDecision(
        candidate_name="seed24_micro_recovery",
        status="candidate_recovery",
    )
    card = schemas.EvidenceCard(
        name="seed24_micro_recovery",
        type="recovery",
        summary="Rescued seed 24 and 198 without regressing baseline.",
        promotion_decision=decision,
        allowed_claims=["paired no-regression rescue"],
        blocked_claims=["transferable skill"],
    )
    assert card.name == "seed24_micro_recovery"
    assert card.promotion_decision.status == "candidate_recovery"


def test_run_artifact_is_evaluation_result():
    artifact = schemas.RunArtifact(
        run_id="r1",
        task_id="t1",
        policy_id="p1",
        adapter="arena",
        status="success",
    )
    assert artifact.run_id == "r1"
    assert artifact.metric_scope == schemas.MetricScope.arena_real


def test_canonical_imports_still_work():
    """Old direct imports must continue to work."""
    from rosclaw_darwin.evaluation.object_validity import (
        ObjectValidityReport as Direct,
    )
    from rosclaw_darwin.schemas import ObjectValidityReport as Reexported

    assert Direct is Reexported
