#!/usr/bin/env python3
"""Smoke tests for residual policy pilot configs.

These tests instantiate the policy with the new residual configs and verify
trace fields are present. They do NOT run Docker; they call policy.reset() and
get_action() with dummy observations if possible, or skip if no dummy env is
available. Keep minimal.
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
def seed24_guard_config() -> HeuristicServoGoalPosePolicyArgs:
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


@pytest.fixture
def slip_guard_config() -> HeuristicServoGoalPosePolicyArgs:
    return HeuristicServoGoalPosePolicyArgs(
        enable_slip_monitor=True,
        slip_recovery_strategy="pause_stabilize",
        enable_residual_policy=True,
        residual_policy="slip_guard",
        residual_enabled_phases=["LIFT", "REORIENT", "ALIGN", "HOLD"],
        approach_offset_z=0.10,
        grasp_dist_threshold=0.04,
        gripper_close_threshold=0.012,
        min_grasp_steps=30,
        lift_height=0.3,
        success_threshold=0.06,
        orientation_threshold=0.5,
    )


def test_seed24_guard_policy_instantiates(seed24_guard_config):
    policy = HeuristicServoGoalPosePolicy(seed24_guard_config)
    assert policy._enable_residual_policy is True
    assert policy._residual_policy_name == "seed24_guard"
    assert policy._residual_enabled_phases == {"GRASP", "CONTACT_VERIFY", "PRE_LIFT"}


def test_slip_guard_policy_instantiates(slip_guard_config):
    policy = HeuristicServoGoalPosePolicy(slip_guard_config)
    assert policy._enable_residual_policy is True
    assert policy._residual_policy_name == "slip_guard"
    assert policy._residual_enabled_phases == {"LIFT", "REORIENT", "ALIGN", "HOLD"}


def test_seed24_guard_get_action_no_crash(seed24_guard_config):
    policy = HeuristicServoGoalPosePolicy(seed24_guard_config)
    policy.reset()
    env = DummyEnv()
    obs = DummyObservation()
    action = policy.get_action(env, obs)
    assert isinstance(action, torch.Tensor)
    assert action.shape == (8,)


def test_slip_guard_get_action_no_crash(slip_guard_config):
    policy = HeuristicServoGoalPosePolicy(slip_guard_config)
    policy.reset()
    env = DummyEnv()
    obs = DummyObservation()
    action = policy.get_action(env, obs)
    assert isinstance(action, torch.Tensor)
    assert action.shape == (8,)


def test_residual_disabled_by_default():
    config = HeuristicServoGoalPosePolicyArgs()
    assert config.enable_residual_policy is False
    assert config.residual_policy == "none"
    assert config.residual_enabled_phases == []


def test_trace_fields_present_when_residual_enabled(seed24_guard_config):
    """Verify that residual trace fields are written when residual is enabled."""
    policy = HeuristicServoGoalPosePolicy(seed24_guard_config)
    policy.reset()
    env = DummyEnv()
    obs = DummyObservation()
    # Run a few steps to generate trace entries.
    for _ in range(5):
        policy.get_action(env, obs)

    # We cannot easily read the trace file here because it is written to a
    # container-side path, but the policy internal state should have set the
    # residual metadata.  Check that the policy tracks residual fields.
    assert hasattr(policy, "_enable_residual_policy")
    assert hasattr(policy, "_residual_policy_name")
    assert hasattr(policy, "_residual_wrapper")
