"""Tests for result semantics metadata."""

from __future__ import annotations

from rosclaw_darwin.evaluation.policy_metadata import PolicyMetadata, load_policy_metadata
from rosclaw_darwin.evaluation.result import ClaimLevel, EvaluationResult, MetricScope


def test_default_arena_result_claims_capability():
    result = EvaluationResult(
        run_id="r1",
        task_id="t1",
        policy_id="heuristic_servo_lift",
        adapter="arena",
        status="completed",
        metrics={"success_rate": 0.0, "progress_mean": 0.3},
    )
    assert result.metric_scope == MetricScope.arena_real
    assert result.claim_level == ClaimLevel.capability
    assert result.can_claim_capability is True
    assert result.can_claim_evolution is False
    assert result.leaderboard_excluded is False


def test_mock_result_is_infrastructure_only():
    result = EvaluationResult(
        run_id="r1",
        task_id="t1",
        policy_id="zero",
        adapter="mock",
        status="completed",
        metrics={"success_rate": 0.0},
        metric_scope=MetricScope.mock_ci,
        claim_level=ClaimLevel.infrastructure,
        can_claim_capability=False,
    )
    assert result.metric_scope == MetricScope.mock_ci
    assert result.claim_level == ClaimLevel.infrastructure
    assert result.can_claim_capability is False


def test_evolution_result_can_claim_evolution():
    result = EvaluationResult(
        run_id="r1",
        task_id="t1",
        policy_id="heuristic_servo_lift",
        adapter="arena",
        status="completed",
        metrics={"success_rate": 0.0, "progress_mean": 0.45},
        metric_scope=MetricScope.arena_real,
        claim_level=ClaimLevel.evolution,
        can_claim_capability=True,
        can_claim_evolution=True,
    )
    assert result.claim_level == ClaimLevel.evolution
    assert result.can_claim_evolution is True


def test_policy_metadata_detects_oracle_from_flat_fields():
    meta = PolicyMetadata.from_policy_config({
        "policy_id": "cheat_lift",
        "type": "cheat_lift",
        "is_oracle": True,
        "is_cheat": True,
        "excluded_from_leaderboard": True,
        "can_claim_capability": False,
    })
    assert meta.is_oracle is True
    assert meta.excluded_from_leaderboard is True
    assert meta.can_claim_capability is False
    assert meta.can_discover_skill is False


def test_policy_metadata_detects_oracle_from_metadata_block():
    meta = PolicyMetadata.from_policy_config({
        "policy_id": "cheat_lift",
        "type": "cheat_lift",
        "policy_metadata": {
            "is_cheat": True,
            "description": "sanity check only",
        },
    })
    assert meta.is_cheat is True
    assert meta.excluded_from_leaderboard is True


def test_apply_exclusion_clears_skill_and_evolution_metrics():
    result = EvaluationResult(
        run_id="r1",
        task_id="t1",
        policy_id="cheat_lift",
        adapter="arena",
        status="completed",
        metrics={
            "success_rate": 1.0,
            "skill_discovery_rate": 1.0,
            "evolution_score": 0.5,
            "skill_candidate_count": 3.0,
        },
    )
    meta = PolicyMetadata(
        policy_id="cheat_lift",
        is_oracle=True,
        is_cheat=True,
        excluded_from_leaderboard=True,
        description="sanity check",
    )
    meta.apply_exclusion(result)

    assert result.metric_scope == MetricScope.pipeline_sanity
    assert result.claim_level == ClaimLevel.infrastructure
    assert result.leaderboard_excluded is True
    assert result.can_claim_capability is False
    assert result.can_claim_evolution is False
    assert "skill_discovery_rate" not in result.metrics
    assert "evolution_score" not in result.metrics
    assert "skill_candidate_count" not in result.metrics


def test_load_policy_metadata_accepts_path(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        "policy_id: p1\n"
        "type: heuristic\n"
        "is_oracle: true\n"
        "excluded_from_leaderboard: true\n"
    )
    meta = load_policy_metadata(path)
    assert meta.is_oracle is True
    assert meta.excluded_from_leaderboard is True


def test_load_policy_metadata_unknown_is_normal():
    meta = load_policy_metadata({"policy_id": "p1", "type": "heuristic"})
    assert meta.is_oracle is False
    assert meta.excluded_from_leaderboard is False
    assert meta.can_claim_capability is True
