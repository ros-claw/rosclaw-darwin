"""Integration tests for the closed-loop servo lift policy.

These tests run on the host by importing the container-side policy file.
The policy file has a fallback PolicyBase stub so it does not require
IsaacLab-Arena to be installed locally.
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np

from rosclaw_darwin.evaluation.arena_docker_deps.heuristic_policy import (
    HeuristicServoGoalPosePolicy,
    HeuristicServoGoalPosePolicyArgs,
    HeuristicServoLiftPolicy,
    HeuristicServoLiftPolicyArgs,
)


class SimpleDeltaEnv:
    """Minimal environment where action[:3] is an absolute target position."""

    def __init__(self, action_shape=(8,), device="cpu"):
        self.device = device
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=action_shape, dtype=float)
        self.unwrapped = self
        self._eef_pos = np.array([0.45, 0.0, 0.35], dtype=float)
        self._object_pos = np.array([0.35, 0.0, 0.07], dtype=float)
        self._gripper_pos = np.array([0.04], dtype=float)
        self._step_count = 0

    def reset(self):
        self._eef_pos = np.array([0.45, 0.0, 0.35], dtype=float)
        self._gripper_pos = np.array([0.04], dtype=float)
        self._step_count = 0
        return self._get_obs()

    def step(self, action):
        self._step_count += 1
        a = action.detach().cpu().numpy() if hasattr(action, "detach") else np.asarray(action)
        if a.ndim > 1:
            a = a[0]
        # Move eef toward the commanded absolute target (mimics absolute-pose IK).
        self._eef_pos += (np.asarray(a[:3], dtype=float) - self._eef_pos) * 0.1
        gripper_cmd = float(a[-1]) if len(a) > 0 else 1.0
        if gripper_cmd < 0:
            self._gripper_pos[0] = max(self._gripper_pos[0] - 0.008, 0.0)
        else:
            self._gripper_pos[0] = min(self._gripper_pos[0] + 0.008, 0.04)
        # Success: end-effector is high while gripper is closed.
        success = self._eef_pos[2] > 0.25 and self._gripper_pos[0] < 0.02
        return self._get_obs(), 1.0 if success else 0.0, success, False, {}

    def _get_obs(self):
        return {
            "policy": {
                "eef_pos": self._eef_pos.copy(),
                "object_pos": self._object_pos.copy(),
                "gripper_pos": self._gripper_pos.copy(),
            }
        }


def _make_obs(eef_pos, object_pos, gripper_pos):
    return {
        "policy": {
            "eef_pos": np.asarray(eef_pos, dtype=float),
            "object_pos": np.asarray(object_pos, dtype=float),
            "gripper_pos": np.asarray([gripper_pos], dtype=float),
        }
    }


def test_servo_policy_action_points_toward_object():
    env = SimpleDeltaEnv(action_shape=(8,))
    policy = HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs())
    eef = np.array([0.50, 0.0, 0.50], dtype=float)
    obj = np.array([0.35, 0.0, 0.07], dtype=float)
    obs = _make_obs(eef, obj, 0.04)
    action = policy.get_action(env, obs)

    assert action.shape == env.action_space.shape
    # In mock mode the policy emits an absolute target pose. The commanded
    # position should lie between the current eef and the object (closer to
    # the object than the current eef is).
    assert abs(action[..., 0].item() - obj[0]) < abs(eef[0] - obj[0]), "should move -x toward object"
    assert abs(action[..., 2].item() - obj[2]) < abs(eef[2] - obj[2]), "should descend toward object"
    assert action[..., 2].item() > obj[2], "should stay above object surface"
    assert action[..., -1].item() > 0, "gripper should be open during approach"


def test_servo_policy_reaches_lift_target():
    env = SimpleDeltaEnv(action_shape=(8,))
    policy = HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs())
    obs = env.reset()
    success = False
    for _ in range(200):
        action = policy.get_action(env, obs)
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated:
            success = True
            break
    assert success, f"expected lift success, final eef z={env._eef_pos[2]:.3f}"


def test_servo_policy_handles_seven_dim_action_space():
    env = SimpleDeltaEnv(action_shape=(7,))
    policy = HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs())
    obs = env.reset()
    action = policy.get_action(env, obs)
    assert action.shape == (7,)


def test_skill_hints_adjust_parameters():
    base = HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs())
    hinted = HeuristicServoLiftPolicy(
        HeuristicServoLiftPolicyArgs(skill_hints=["grasp_adjust", "efficient_execution"])
    )
    assert hinted._kp > base._kp
    assert hinted._approach_offset_z < base._approach_offset_z
    assert hinted._grasp_dist_threshold > base._grasp_dist_threshold


def test_servo_policy_logs_hint_consumption(capsys):
    env = SimpleDeltaEnv(action_shape=(8,))
    policy = HeuristicServoLiftPolicy(
        HeuristicServoLiftPolicyArgs(skill_hints=["grasp_adjust"])
    )
    obs = env.reset()
    policy.get_action(env, obs)
    captured = capsys.readouterr()
    assert "HEURISTIC_SKILL_HINTS" in captured.err
    assert "grasp_adjust" in captured.err


def test_goal_pose_policy_imports_and_runs():
    env = SimpleDeltaEnv(action_shape=(8,))
    policy = HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs())
    obs = env.reset()
    action = policy.get_action(env, obs)
    assert action.shape == env.action_space.shape


def test_goal_pose_policy_skill_hints_adjust_parameters():
    base = HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs())
    hinted = HeuristicServoGoalPosePolicy(
        HeuristicServoGoalPosePolicyArgs(skill_hints=["target_tracking", "release_at_target"])
    )
    assert hinted._lift_kp_multiplier > base._lift_kp_multiplier
    assert hinted._min_release_steps > base._min_release_steps
