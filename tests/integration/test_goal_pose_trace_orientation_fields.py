"""Integration tests for goal_pose trace orientation fields.

These tests run the policy against a minimal scene-backed environment and
verify that the resulting trace file contains the v2 orientation fields.
"""

from __future__ import annotations

import json

import gymnasium as gym
import pytest
import torch

from rosclaw_darwin.evaluation.arena_docker_deps import heuristic_policy
from rosclaw_darwin.evaluation.arena_docker_deps.heuristic_policy import (
    HeuristicServoGoalPosePolicy,
    HeuristicServoGoalPosePolicyArgs,
)


@pytest.fixture
def trace_env(tmp_path, monkeypatch):
    """Provide a policy and an environment; redirect trace to tmp_path."""
    monkeypatch.setattr(heuristic_policy, "_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(heuristic_policy, "_TRACE_PATH", str(tmp_path / "episode_trace.jsonl"))
    monkeypatch.setattr(heuristic_policy, "_TRACE_METADATA_WRITTEN", False)

    env = _SceneBackedEnv()
    policy = HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs())
    yield env, policy, tmp_path


class _SceneBackedEnv:
    """Tiny environment whose unwrapped.scene exposes ee_frame/dex_cube/robot."""

    def __init__(self):
        self.device = "cpu"
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(7,), dtype=float)
        self.unwrapped = self
        self._step = 0
        self.scene = self._make_scene()

    def _make_scene(self):
        from types import SimpleNamespace

        eef_pos = torch.tensor([[0.35, 0.0, 0.30]], dtype=torch.float32)
        eef_quat = torch.tensor([[0.0, 0.0, 0.0, 1.0]], dtype=torch.float32)
        object_pos = torch.tensor([[0.35, 0.0, 0.07]], dtype=torch.float32)
        object_quat = torch.tensor([[0.0, 0.0, 0.0, 1.0]], dtype=torch.float32)
        joints = torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.04, 0.04]], dtype=torch.float32)

        ee_frame = SimpleNamespace(
            data=SimpleNamespace(target_pos_w=eef_pos, source_quat_w=eef_quat)
        )
        dex_cube = SimpleNamespace(
            data=SimpleNamespace(root_pos_w=object_pos, root_quat_w=object_quat)
        )
        robot = SimpleNamespace(data=SimpleNamespace(joint_pos=joints))

        return {
            "ee_frame": ee_frame,
            "dex_cube": dex_cube,
            "robot": robot,
        }

    def reset(self):
        self._step = 0
        return {"policy": {}}

    def step(self, action):
        self._step += 1
        return {"policy": {}}, 0.0, self._step > 300, False, {}


def test_multi_step_trace_has_orientation_fields(trace_env):
    env, policy, tmp_path = trace_env
    obs = env.reset()
    for _ in range(5):
        action = policy.get_action(env, obs)
        obs, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break

    trace_path = tmp_path / "episode_trace.jsonl"
    assert trace_path.exists()
    lines = trace_path.read_text().strip().splitlines()
    assert len(lines) >= 5

    for line in lines:
        rec = json.loads(line)
        for key in (
            "eef_roll",
            "eef_pitch",
            "eef_yaw",
            "desired_eef_yaw",
            "eef_yaw_error",
            "object_yaw",
            "target_yaw",
            "object_yaw_error",
            "action_rot_x",
            "action_rot_y",
            "action_rot_z",
        ):
            assert key in rec, f"missing orientation field: {key}"


def test_trace_phase_matches_policy_state(trace_env):
    env, policy, tmp_path = trace_env
    obs = env.reset()
    for _ in range(5):
        action = policy.get_action(env, obs)
        env.step(action)

    trace_path = tmp_path / "episode_trace.jsonl"
    phases = [json.loads(line)["phase"] for line in trace_path.read_text().strip().splitlines()]
    assert phases[0] == "APPROACH"
    assert all(isinstance(p, str) for p in phases)
