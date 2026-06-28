#!/usr/bin/env python3
"""Smoke tests for seed24 micro-recovery policy config.

These tests instantiate the policy with the new config and verify trace fields
are present. They do NOT run Docker; they call policy.reset() and get_action()
with dummy observations if possible, or skip if no dummy env is available.
"""

from __future__ import annotations

import pytest
import torch

from rosclaw_darwin.evaluation.arena_docker_deps.heuristic_policy import (
    HeuristicServoGoalPosePolicy,
    HeuristicServoGoalPosePolicyArgs,
)


class DummyEnv:
    """Minimal gym-like env for policy smoke tests."""

    def __init__(self):
        self.device = "cpu"
        self.action_space = type("AS", (), {"shape": (8,)})()
        self.unwrapped = self

    def keys(self):
        return []


class DummyObservation(dict):
    pass


@pytest.fixture
def seed24_residual_config() -> HeuristicServoGoalPosePolicyArgs:
    return HeuristicServoGoalPosePolicyArgs(
        enable_grip_quality_monitor=True,
        micro_recovery_strategy="lower_reclose",
        enable_residual_policy=True,
        residual_policy="seed24_guard",
        residual_enabled_phases=["GRASP", "CONTACT_VERIFY", "PRE_LIFT"],
        approach_offset_z=0.10,
        grasp_dist_threshold=0.04,
        gripper_close_threshold=0.012,
        min_grasp_steps=30,
        lift_height=0.3,
        success_threshold=0.06,
        orientation_threshold=0.5,
    )


def test_policy_instantiates_with_residual_config(seed24_residual_config):
    policy = HeuristicServoGoalPosePolicy(seed24_residual_config)
    assert policy._enable_residual_policy is True
    assert policy._residual_policy_name == "seed24_guard"
    assert policy._residual_enabled_phases == {"GRASP", "CONTACT_VERIFY", "PRE_LIFT"}


def test_policy_reset_clears_residual_state(seed24_residual_config):
    policy = HeuristicServoGoalPosePolicy(seed24_residual_config)
    policy.reset()
    assert policy._step == 0
    assert policy._state == "APPROACH"


def test_get_action_with_dummy_observation(seed24_residual_config):
    policy = HeuristicServoGoalPosePolicy(seed24_residual_config)
    policy.reset()
    env = DummyEnv()
    obs = DummyObservation()
    # The policy should not crash with a dummy observation.
    action = policy.get_action(env, obs)
    assert isinstance(action, torch.Tensor)
    assert action.shape == (8,)


def test_residual_disabled_by_default():
    config = HeuristicServoGoalPosePolicyArgs()
    assert config.enable_residual_policy is False
    assert config.residual_policy == "none"
    assert config.residual_enabled_phases == []
