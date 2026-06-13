"""Tests for oracle/cheat policy exclusion from leaderboard and skill metrics."""

from __future__ import annotations

from pathlib import Path

from rosclaw_darwin.evaluation.policy_metadata import load_policy_metadata
from rosclaw_darwin.evaluation.result import ClaimLevel, EvaluationResult, MetricScope

CONFIG_PATH = Path(__file__).parents[2] / "configs" / "policies" / "cheat_lift.yaml"


def test_cheat_lift_config_is_oracle():
    assert CONFIG_PATH.exists(), f"Config not found: {CONFIG_PATH}"
    meta = load_policy_metadata(CONFIG_PATH)
    assert meta.policy_id == "cheat_lift"
    assert meta.is_oracle is True
    assert meta.is_cheat is True
    assert meta.excluded_from_leaderboard is True
    assert meta.can_claim_capability is False
    assert meta.can_discover_skill is False
    assert meta.can_compute_evolution_score is False


def test_cheat_lift_result_is_excluded():
    meta = load_policy_metadata(CONFIG_PATH)
    result = EvaluationResult(
        run_id="r1",
        task_id="darwin_mvp_03_lift_object",
        policy_id="cheat_lift",
        adapter="arena",
        status="completed",
        metrics={"success_rate": 1.0},
    )
    meta.apply_exclusion(result)

    assert result.metric_scope == MetricScope.pipeline_sanity
    assert result.claim_level == ClaimLevel.infrastructure
    assert result.leaderboard_excluded is True
    assert result.can_claim_capability is False
    assert result.can_claim_evolution is False
    assert result.metrics["success_rate"] == 1.0
    assert "skill_discovery_rate" not in result.metrics
    assert "evolution_score" not in result.metrics


def test_normal_policy_not_excluded():
    meta = load_policy_metadata({
        "policy_id": "heuristic_servo_lift",
        "type": "heuristic_servo_lift",
        "policy_config_dict": {"kp": 5.0},
    })
    result = EvaluationResult(
        run_id="r2",
        task_id="darwin_mvp_03_lift_object",
        policy_id="heuristic_servo_lift",
        adapter="arena",
        status="completed",
        metrics={"success_rate": 0.0, "progress_mean": 0.3},
    )
    meta.apply_exclusion(result)

    assert result.leaderboard_excluded is False
    assert result.can_claim_capability is True
    assert result.metric_scope == MetricScope.arena_real


def test_oracle_exclusion_description_is_preserved():
    meta = load_policy_metadata(CONFIG_PATH)
    assert "sanity" in meta.description.lower()
    assert "leaderboard" in meta.description.lower()
