# Heuristic lift policy for Arena Docker evaluation.
# Uses delta pose control (Franka IK relative mode, scale=0.5).
# Called dynamically by eval_runner via policy_type module path.

import argparse
import gymnasium as gym
import torch
from dataclasses import dataclass
from gymnasium.spaces.dict import Dict as GymSpacesDict

from isaaclab_arena.policy.policy_base import PolicyBase


@dataclass
class HeuristicLiftPolicyArgs:
    """Configuration for HeuristicLiftPolicy (no hyperparameters)."""

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicLiftPolicyArgs":
        return cls()


class HeuristicLiftPolicy(PolicyBase):
    """Fixed-sequence heuristic policy for lift_object with delta IK control.

    Action mapping for FrankaIK relative mode (scale=0.5):
      action[:3]  = delta position  (actual delta = action * 0.5)
      action[3:7] = delta quaternion (actual delta = action * 0.5)
      action[7]   = gripper command
    """

    name = "heuristic_lift"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)

        step = self._step
        self._step += 1

        # Delta per step (will be multiplied by scale=0.5 inside controller)
        delta_z = 0.04

        if step < 30:
            # Phase 1: descend toward object
            action[..., 2] = -delta_z
            action[..., -1] = 1.0   # gripper open
        elif step < 40:
            # Phase 2: close gripper at object height
            action[..., 2] = 0.0
            action[..., -1] = -1.0  # gripper close
        elif step < 80:
            # Phase 3: lift up
            action[..., 2] = delta_z
            action[..., -1] = -1.0  # gripper close
        else:
            # Phase 4: hold
            action[..., 2] = 0.0
            action[..., -1] = -1.0

        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicLiftPolicy":
        return HeuristicLiftPolicy(HeuristicLiftPolicyArgs.from_cli_args(args))


class CubeGoalPoseHeuristicPolicy(PolicyBase):
    """Heuristic for cube_goal_pose: grasp, lift, and rotate yaw 90°.

    Target orientation (0,0,0.7071,0.7071) = yaw 90°.
    With relative IK mode and scale=0.5, action = 2 * delta_quat.
    """

    name = "cube_goal_pose_heuristic"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1

        delta_z = 0.04
        target_qz = 1.4142  # 0.7071 * 2
        target_qw = 1.4142

        if step < 30:
            # descend
            action[..., 2] = -delta_z
            action[..., -1] = 1.0
        elif step < 40:
            # grasp
            action[..., 2] = 0.0
            action[..., -1] = -1.0
        elif step < 50:
            # rotate yaw 90° (no translation)
            action[..., 5] = target_qz
            action[..., 6] = target_qw
            action[..., -1] = -1.0
        elif step < 80:
            # lift up
            action[..., 2] = delta_z
            action[..., -1] = -1.0
        else:
            # hold
            action[..., 2] = 0.0
            action[..., -1] = -1.0
        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "CubeGoalPoseHeuristicPolicy":
        return CubeGoalPoseHeuristicPolicy(HeuristicLiftPolicyArgs.from_cli_args(args))
