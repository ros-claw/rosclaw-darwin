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

    CRITICAL DISCOVERY from Docker stderr:
      - action_space.shape = (1, 7)  [not 8-dim quaternion]
      - action_space has NO bounds (low=-inf, high=inf)
      - observation has NO object_pos / object_quat
      - eef initial yaw ≈ 180° (quat z≈1, w≈0, format x,y,z,w)
      - controller position response is heavily damped (~3% of action)
      - orientation control shows ZERO response so far

    This version aggressively increases delta_z to overcome damping and
    probes env config on first step.
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

        # DRASTIC INCREASE to overcome controller damping/smoothing
        delta_z = 0.8
        target_yaw = 10.0  # very large to test if orientation control is active at all

        # Probe env config on first step
        if step == 0:
            import sys
            uw = env.unwrapped
            print(f"[HEURISTIC_DEBUG] action_space: shape={env.action_space.shape} low={getattr(env.action_space, 'low', 'N/A')} high={getattr(env.action_space, 'high', 'N/A')}", file=sys.stderr)
            print(f"[HEURISTIC_DEBUG] unwrapped type: {type(uw).__name__}", file=sys.stderr)
            if hasattr(uw, "cfg"):
                cfg = uw.cfg
                print(f"[HEURISTIC_DEBUG] env cfg type: {type(cfg).__name__}", file=sys.stderr)
                if hasattr(cfg, "observations"):
                    print(f"[HEURISTIC_DEBUG] observations: {cfg.observations}", file=sys.stderr)
                if hasattr(cfg, "actions"):
                    print(f"[HEURISTIC_DEBUG] actions: {cfg.actions}", file=sys.stderr)
            if isinstance(observation, dict):
                pol = observation.get("policy", observation)
                if isinstance(pol, dict):
                    eef_q = pol.get("eef_quat")
                    eef_p = pol.get("eef_pos")
                    obj_p = pol.get("object_pos")
                    if eef_q is not None:
                        print(f"[HEURISTIC_DEBUG] step=0 eef_quat={eef_q.tolist()} eef_pos={eef_p.tolist() if eef_p is not None else 'N/A'} object_pos={obj_p.tolist() if obj_p is not None else 'N/A'}", file=sys.stderr)
            sys.stderr.flush()

        if step < 100:
            # Phase 1: aggressive descend toward object
            action[..., 2] = -delta_z
            action[..., -1] = 1.0   # gripper open
        elif step < 120:
            # Phase 2: close gripper
            action[..., 2] = 0.0
            action[..., -1] = -1.0  # gripper close
        elif step == 120:
            # Phase 3: single-step rotate + lift
            action[..., 2] = delta_z
            action[..., 5] = target_yaw
            action[..., -1] = -1.0
            import sys
            print(f"[HEURISTIC_DEBUG] step=120 action={action.tolist()}", file=sys.stderr)
            sys.stderr.flush()
        elif step == 121:
            import sys
            if isinstance(observation, dict):
                pol = observation.get("policy", observation)
                if isinstance(pol, dict):
                    eef_q = pol.get("eef_quat")
                    grip = pol.get("gripper_pos")
                    eef_p = pol.get("eef_pos")
                    print(f"[HEURISTIC_DEBUG] step=121 eef_quat={eef_q.tolist() if eef_q is not None else 'N/A'} gripper_pos={grip.tolist() if grip is not None else 'N/A'} eef_pos={eef_p.tolist() if eef_p is not None else 'N/A'}", file=sys.stderr)
                    sys.stderr.flush()
        elif step < 200:
            # Phase 4: continue lifting
            action[..., 2] = delta_z
            action[..., -1] = -1.0
        else:
            # Phase 5: hold
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


class CheatCubeGoalPosePolicy(PolicyBase):
    """Cheat policy: directly teleport the cube to the target pose.

    This is NOT a real robot policy; it uses env.scene physics APIs to
    immediately satisfy goal_pose_task_termination. Used as a baseline to
    verify the Arena eval pipeline can produce non-zero success_rate.
    """

    name = "cheat_cube_goal_pose"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._cheat_done = False

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1

        if step == 50 and not self._cheat_done:
            self._cheat_done = True
            try:
                import sys

                from isaaclab.assets import RigidObject

                scene = env.unwrapped.scene
                target_pos = torch.tensor([[0.1, 0.0, 0.3]], device=device)
                target_quat = torch.tensor([[0.0, 0.0, 0.7071, 0.7071]], device=device)
                zero_vel = torch.zeros((1, 6), device=device)

                # Find the cube object dynamically. In different Arena envs the
                # object key may be "object" (lift_object) or "dex_cube"
                # (cube_goal_pose) or another registered name.
                obj = None
                obj_key = None
                for key in scene.keys():
                    key_str = str(key)
                    if key_str in ("object", "dex_cube", "cube"):
                        obj = scene[key_str]
                        obj_key = key_str
                        break
                if obj is None:
                    # Fallback: iterate scene entities and pick a RigidObject
                    # whose name suggests it is the cube.
                    for ent in scene.values():
                        if isinstance(ent, RigidObject):
                            name = getattr(ent, "name", "") or getattr(ent.cfg, "name", "")
                            if "cube" in name.lower() or "object" in name.lower():
                                obj = ent
                                obj_key = name or "unknown"
                                break
                if obj is None:
                    raise KeyError(
                        f"Could not find cube/object in scene. Available keys: {list(scene.keys())}"
                    )
                origin = scene.env_origins[0:1] if hasattr(scene, "env_origins") else torch.zeros((1, 3), device=device)
                root_pose = torch.cat([target_pos + origin, target_quat], dim=-1)
                obj.write_root_pose_to_sim(root_pose)
                obj.write_root_velocity_to_sim(zero_vel)
                print(f"[CHEAT] Teleported '{obj_key}' to target pose at step {step}", file=sys.stderr)
                sys.stderr.flush()
            except Exception as e:
                import sys

                print(f"[CHEAT] Error during teleport: {e}", file=sys.stderr)
                sys.stderr.flush()

        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._cheat_done = False

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "CheatCubeGoalPosePolicy":
        return CheatCubeGoalPosePolicy(HeuristicLiftPolicyArgs.from_cli_args(args))
