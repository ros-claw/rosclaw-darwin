"""Unit tests for goal_pose trace schema v2.

These tests verify that ``HeuristicServoGoalPosePolicy`` writes the enriched
trace fields required for physical diagnosis: end-effector rpy/yaw, object
yaw error, and rotational action components.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import torch

from rosclaw_darwin.evaluation.arena_docker_deps import heuristic_policy
from rosclaw_darwin.evaluation.arena_docker_deps.heuristic_policy import (
    HeuristicServoGoalPosePolicy,
    HeuristicServoGoalPosePolicyArgs,
)


@pytest.fixture(autouse=True)
def _reset_trace_state(monkeypatch, tmp_path):
    """Redirect trace output to a temp directory for every test."""
    monkeypatch.setattr(heuristic_policy, "_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(heuristic_policy, "_TRACE_PATH", str(tmp_path / "episode_trace.jsonl"))
    monkeypatch.setattr(heuristic_policy, "_TRACE_METADATA_WRITTEN", False)
    yield


class _MinimalEnv:
    """Minimal environment with a scene that supplies ee/object/robot data."""

    def __init__(self):
        import gymnasium as gym

        self.device = "cpu"
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(7,), dtype=float)
        self.unwrapped = self
        self._step = 0

        self.scene = self._build_scene()

    def _build_scene(self):
        from types import SimpleNamespace

        eef_pos = torch.tensor([[0.35, 0.0, 0.25]], dtype=torch.float32)
        eef_quat = torch.tensor([[0.0, 0.0, 0.0, 1.0]], dtype=torch.float32)
        object_pos = torch.tensor([[0.35, 0.0, 0.07]], dtype=torch.float32)
        object_quat = torch.tensor([[0.0, 0.0, 0.0, 1.0]], dtype=torch.float32)
        joints = torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.04, 0.04]], dtype=torch.float32)

        ee_data = SimpleNamespace(
            target_pos_w=eef_pos,
            source_quat_w=eef_quat,
        )
        ee_frame = SimpleNamespace(data=ee_data)

        cube_data = SimpleNamespace(
            root_pos_w=object_pos,
            root_quat_w=object_quat,
        )
        cube = SimpleNamespace(data=cube_data)

        robot_data = SimpleNamespace(joint_pos=joints)
        robot = SimpleNamespace(data=robot_data)

        scene = {
            "ee_frame": ee_frame,
            "dex_cube": cube,
            "robot": robot,
        }
        return scene

    def reset(self):
        self._step = 0
        return {"policy": {}}

    def step(self, action):
        self._step += 1
        return {"policy": {}}, 0.0, self._step > 200, False, {}


def test_trace_metadata_written(tmp_path):
    HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs())
    meta_path = tmp_path / "trace_metadata.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text())
    assert data["trace_schema_version"] == "goal_pose_trace_v2"
    assert data["eef_yaw_recorded"] is True
    assert "object_yaw_error_to_target_yaw" in data["orientation_error_definition"]


def test_trace_contains_v2_fields(tmp_path):
    env = _MinimalEnv()
    policy = HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs())
    obs = env.reset()
    action = policy.get_action(env, obs)
    assert action.shape == env.action_space.shape

    trace_path = tmp_path / "episode_trace.jsonl"
    assert trace_path.exists()
    lines = trace_path.read_text().strip().splitlines()
    assert len(lines) >= 1
    rec = json.loads(lines[0])

    for key in (
        "eef_qx",
        "eef_qy",
        "eef_qz",
        "eef_qw",
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
        assert key in rec, f"missing trace field: {key}"


def test_quat_to_rpy_identity():
    # Policy quaternion convention is (x, y, z, w).
    q = torch.tensor([0.0, 0.0, 0.0, 1.0], dtype=torch.float32)
    roll, pitch, yaw = HeuristicServoGoalPosePolicy._quat_to_rpy(q)
    assert abs(roll) < 1e-6
    assert abs(pitch) < 1e-6
    assert abs(yaw) < 1e-6


def test_quat_to_rpy_yaw_90_degrees():
    # (x, y, z, w): 90 deg yaw = (0, 0, sin45, cos45)
    q = torch.tensor([0.0, 0.0, math.sqrt(2) / 2, math.sqrt(2) / 2], dtype=torch.float32)
    roll, pitch, yaw = HeuristicServoGoalPosePolicy._quat_to_rpy(q)
    assert abs(roll) < 1e-6
    assert abs(pitch) < 1e-6
    assert abs(yaw - math.pi / 2) < 1e-6


def test_angle_diff_wraps():
    diff = HeuristicServoGoalPosePolicy._angle_diff(math.pi - 0.1, -math.pi + 0.1)
    assert abs(diff - (-0.2)) < 1e-6


def test_object_yaw_error_computed():
    """A non-trivial object yaw should produce a non-zero object_yaw_error."""
    env = _MinimalEnv()
    # Rotate cube 45 deg around z (x, y, z, w convention).
    yaw = math.pi / 4
    env.scene["dex_cube"].data.root_quat_w = torch.tensor(
        [[0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)]], dtype=torch.float32
    )

    args = HeuristicServoGoalPosePolicyArgs(
        fixed_target_pos=[0.35, 0.0, 0.30],
        fixed_target_quat=[0.0, 0.0, math.sqrt(2) / 2, math.sqrt(2) / 2],
    )
    policy = HeuristicServoGoalPosePolicy(args)
    obs = env.reset()
    policy.get_action(env, obs)

    trace_path = Path(heuristic_policy._TRACE_PATH)
    rec = json.loads(trace_path.read_text().strip().splitlines()[0])
    assert rec["object_yaw"] is not None
    assert abs(rec["object_yaw"] - yaw) < 1e-5
    assert rec["object_yaw_error"] is not None
    assert abs(rec["object_yaw_error"]) > 0.01
