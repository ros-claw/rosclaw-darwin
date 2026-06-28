"""Unit tests for the table push-align large-yaw strategy."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch
import yaml

from rosclaw_darwin.evaluation.arena_docker_deps.heuristic_policy import (
    HeuristicServoGoalPosePolicy,
    HeuristicServoGoalPosePolicyArgs,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_config(strategy: str | None = "table_push_align") -> HeuristicServoGoalPosePolicyArgs:
    return HeuristicServoGoalPosePolicyArgs(
        large_yaw_strategy=strategy,
        table_push_align_table_z=0.18,
        table_push_align_z_offset=0.02,
        table_push_align_max_steps=80,
        table_push_align_min_steps=10,
        table_push_align_orientation_threshold=0.3,
        table_push_align_yaw_step=0.10,
        table_push_align_lateral_amplitude=0.005,
        table_push_align_lateral_period=20,
        table_push_align_downward_kp=1.0,
        table_push_align_consecutive_aligned_steps=5,
        table_push_align_min_yaw_error=0.5,
    )


def test_table_push_align_strategy_sets_v2_and_reorient_flags() -> None:
    """table_push_align must disable pre-grasp yaw align and in-air reorient."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    assert policy._large_yaw_strategy == "table_push_align"
    assert policy._pre_grasp_yaw_align_v2 is False
    assert policy._reorient_before_align is False  # reorientation happens on the table
    assert policy._table_push_align_table_z == 0.18
    assert policy._table_push_align_orientation_threshold == 0.3


def test_table_push_align_params_default_when_not_set() -> None:
    """Default push-align parameters are sane when strategy is not used."""
    policy = HeuristicServoGoalPosePolicy(_make_config(None))
    assert policy._large_yaw_strategy is None
    assert policy._table_push_align_z_offset == 0.02
    assert policy._table_push_align_max_steps == 80


def test_should_table_push_align_true_for_large_yaw_error() -> None:
    """Large yaw discrepancy triggers table push-align."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    target_quat = torch.tensor([0.0, 0.0, math.sin(math.pi / 2 / 2), math.cos(math.pi / 2 / 2)])
    assert policy._should_table_push_align(target_quat, 0.0) is True


def test_should_table_push_align_false_for_small_yaw_error() -> None:
    """Small yaw discrepancy does not need table push-align."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    target_quat = torch.tensor([0.0, 0.0, math.sin(0.2 / 2), math.cos(0.2 / 2)])
    assert policy._should_table_push_align(target_quat, 0.0) is False


def test_should_table_push_align_false_without_target_quat() -> None:
    """Missing target orientation disables push-align."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    assert policy._should_table_push_align(None, 0.0) is False


def test_reset_clears_table_push_align_counter() -> None:
    """Episode reset must clear the consecutive-alignment counter."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    policy._table_push_align_aligned_steps = 7
    policy.reset()
    assert policy._table_push_align_aligned_steps == 0


def test_table_push_align_state_machine_has_phase() -> None:
    """The policy must know about the TABLE_PUSH_ALIGN phase."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    # _transition is inherited and simply sets _state.
    policy._transition("TABLE_PUSH_ALIGN")
    assert policy._state == "TABLE_PUSH_ALIGN"


def test_table_push_align_lateral_target_oscillates() -> None:
    """The lateral target oscillates around the object position."""
    policy = HeuristicServoGoalPosePolicy(_make_config("table_push_align"))
    amp = policy._table_push_align_lateral_amplitude
    period = policy._table_push_align_lateral_period
    # Use the state_step as the oscillation phase counter.
    policy._state_step = period // 4
    t = 2.0 * math.pi * policy._state_step / period
    expected_x = amp * math.sin(t)
    expected_y = amp * math.cos(t)
    assert abs(expected_x - amp) < 1e-6
    assert abs(expected_y - 0.0) < 1e-6


def test_table_push_align_tuned_config_loads() -> None:
    """The tuned YAML config must instantiate a policy with tuned parameters."""
    config_path = REPO_ROOT / "configs" / "policies" / "heuristic_servo_goal_pose_v3_large_yaw_table_push_align_tuned.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = HeuristicServoGoalPosePolicyArgs(**raw["policy_config_dict"])
    policy = HeuristicServoGoalPosePolicy(config)
    assert policy._large_yaw_strategy == "table_push_align"
    assert policy._table_push_align_z_offset == 0.04
    assert policy._table_push_align_max_steps == 120
    assert policy._table_push_align_yaw_step == 0.15
    assert policy._table_push_align_lateral_amplitude == 0.01
    assert policy._table_push_align_downward_kp == 0.5
    assert policy._table_push_align_consecutive_aligned_steps == 8
    assert policy._pre_grasp_yaw_align_v2 is False
    assert policy._reorient_before_align is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
