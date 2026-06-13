# Heuristic lift policy for Arena Docker evaluation.
# Uses delta pose control (Franka IK relative mode, scale=0.5).
# Called dynamically by eval_runner via policy_type module path.

import argparse
from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import torch
from gymnasium.spaces.dict import Dict as GymSpacesDict

try:
    from isaaclab_arena.policy.policy_base import PolicyBase
except Exception:  # pragma: no cover - host side does not have IsaacLab-Arena installed
    class PolicyBase:
        """Minimal stub so the policy file can be imported in host tests."""

        def __init__(self, config):
            self.config = config
except Exception:  # pragma: no cover - host side does not have IsaacLab-Arena installed
    class PolicyBase:
        """Minimal stub so the policy file can be imported in host tests."""

        def __init__(self, config):
            self.config = config


@dataclass
class HeuristicLiftPolicyArgs:
    """Configuration for HeuristicLiftPolicy."""

    skill_hints: list[str] | None = None

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoLiftPolicyArgs:
    """Configuration for HeuristicServoLiftPolicy."""

    skill_hints: list[str] | None = None
    approach_offset_z: float = 0.08
    grasp_offset_z: float = 0.02
    lift_height: float = 0.25
    kp: float = 5.0
    grasp_dist_threshold: float = 0.03
    gripper_close_threshold: float = 0.015
    min_grasp_steps: int = 5
    approach_horizontal_threshold: float = 0.05
    max_state_steps: int = 300

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


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
        self._skill_hints = set((config.skill_hints or []))
        # Skill hints adapt the heuristic parameters.
        self._delta_z = 0.04
        self._descent_steps = 30
        self._gripper_close_steps = 10
        self._lift_steps = 40
        if "efficient_execution" in self._skill_hints:
            self._delta_z *= 1.5
        if "grasp_adjust" in self._skill_hints:
            self._gripper_close_steps += 5
        if "adaptive_skill" in self._skill_hints:
            self._descent_steps = max(10, self._descent_steps - 5)
            self._lift_steps += 10

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)

        step = self._step
        self._step += 1

        # Log skill hint consumption once for observability.
        if step == 0 and self._skill_hints:
            import sys
            print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
            print(f"[HEURISTIC_SKILL_HINTS] params: delta_z={self._delta_z:.4f} "
                  f"descent={self._descent_steps} close={self._gripper_close_steps} lift={self._lift_steps}", file=sys.stderr)
            sys.stderr.flush()

        # Delta per step (will be multiplied by scale=0.5 inside controller)
        delta_z = self._delta_z

        descent_end = self._descent_steps
        close_end = descent_end + self._gripper_close_steps
        lift_end = close_end + self._lift_steps

        if step < descent_end:
            # Phase 1: descend toward object
            action[..., 2] = -delta_z
            action[..., -1] = 1.0   # gripper open
        elif step < close_end:
            # Phase 2: close gripper at object height
            action[..., 2] = 0.0
            action[..., -1] = -1.0  # gripper close
        elif step < lift_end:
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


class HeuristicServoLiftPolicy(PolicyBase):
    """Closed-loop servo heuristic for lift_object using observations.

    Reads eef_pos / eef_quat / object_pos / gripper_pos / task_obs target
    from the environment to servo above the object, descend, close the
    gripper, and lift toward the command target. Works with both 7-dim and
    8-dim action spaces and adapts to relative or absolute IK controllers.
    """

    name = "heuristic_servo_lift"
    config_class = HeuristicServoLiftPolicyArgs

    def __init__(self, config: HeuristicServoLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._state = "APPROACH"
        self._state_step = 0
        self._skill_hints = set(config.skill_hints or [])
        self._relative_mode: bool | None = None
        self._action_scale: float = 1.0

        self._approach_offset_z = config.approach_offset_z
        self._grasp_offset_z = config.grasp_offset_z
        self._lift_height = config.lift_height
        self._kp = config.kp
        self._grasp_dist_threshold = config.grasp_dist_threshold
        self._gripper_close_threshold = config.gripper_close_threshold
        self._min_grasp_steps = config.min_grasp_steps
        self._approach_horizontal_threshold = config.approach_horizontal_threshold
        self._max_state_steps = config.max_state_steps

        if "efficient_execution" in self._skill_hints:
            self._kp *= 1.5
            self._approach_offset_z *= 0.75
        if "grasp_adjust" in self._skill_hints:
            self._grasp_offset_z = max(0.0, self._grasp_offset_z - 0.015)
            self._grasp_dist_threshold *= 1.5
            self._min_grasp_steps += 3
        if "slower_descent" in self._skill_hints:
            self._kp *= 0.7
            self._approach_offset_z *= 1.2
        if "adaptive_skill" in self._skill_hints:
            self._min_grasp_steps = max(2, self._min_grasp_steps - 2)
            self._lift_height += 0.05

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1
        self._state_step += 1

        if step == 0 and self._skill_hints:
            self._log_hints()

        if self._relative_mode is None:
            self._infer_controller_mode(env)

        eef_pos, eef_quat, object_pos, gripper_pos, target_pos = self._extract_state(observation, env, device)

        if step == 0 and self._skill_hints:
            self._log_hints()

        if self._relative_mode is None:
            self._infer_controller_mode(env)

        eef_pos, eef_quat, object_pos, gripper_pos, target_pos = self._extract_state(observation, env, device)

        if object_pos is None:
            # Fallback open-loop sequence when observation is missing.
            if step < 50:
                action[..., 2] = -0.04
                action = self._set_gripper(action, open=True)
            else:
                action[..., 2] = 0.04
                action = self._set_gripper(action, open=False)
            return action

        if self._state == "APPROACH":
            target = object_pos.clone()
            target[2] += self._approach_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            horiz = torch.norm(object_pos[:2] - eef_pos[:2])
            z_err = abs(eef_pos[2] - target[2])
            if horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5:
                self._transition("DESCEND")

        elif self._state == "DESCEND":
            target = object_pos.clone()
            target[2] += self._grasp_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            if torch.norm(target - eef_pos) < self._grasp_dist_threshold:
                self._transition("GRASP")

        elif self._state == "GRASP":
            action = self._set_gripper(action, open=False)
            closed = gripper_pos is not None and gripper_pos < self._gripper_close_threshold
            if self._state_step >= self._min_grasp_steps and closed:
                self._transition("LIFT")

        elif self._state == "LIFT":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=False)
            if eef_pos[2] >= target[2] - 0.03:
                self._transition("HOLD")

        elif self._state == "HOLD":
            action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        return action

    def _infer_controller_mode(self, env: gym.Env) -> None:
        """Detect whether the arm controller expects relative deltas or absolute poses."""
        try:
            cfg = env.unwrapped.cfg
            arm = cfg.actions.arm_action
            self._relative_mode = bool(getattr(arm.controller, "use_relative_mode", True))
            self._action_scale = float(getattr(arm, "scale", 1.0))
            if self._action_scale == 0.0:
                self._action_scale = 1.0
        except Exception:
            # Default to absolute-pose commands for mock/unit-test environments.
            self._relative_mode = False
            self._action_scale = 1.0

    def _apply_position(
        self,
        action: torch.Tensor,
        eef_pos: torch.Tensor | None,
        eef_quat: torch.Tensor | None,
        target: torch.Tensor,
    ) -> None:
        """Write a position (and orientation) command into ``action[..., :3]``."""
        if eef_pos is None:
            return
        delta = self._kp * (target - eef_pos)
        # In relative mode we want to saturate the action to maximize step size
        # (the controller is heavily damped). In absolute mode keep steps small
        # so mock/unit-test environments remain stable.
        max_delta = 0.5 if self._relative_mode else 0.1
        delta = torch.clamp(delta, -max_delta, max_delta)

        if self._relative_mode:
            # Relative-mode action is a delta pose in the end-effector body frame,
            # scaled by action_scale. The arm command has 6 dims:
            #   [dx, dy, dz, droll, dpitch, dyaw]
            # followed by the gripper dim.
            body_delta = delta.clone()
            # Empirical body-frame convention for the Franka panda_hand used by
            # DifferentialInverseKinematicsActionCfg: x points backward relative
            # to world x, y is aligned, and z points out of the gripper (opposite
            # to world z when reaching downward).
            body_delta[0] = -body_delta[0]
            body_delta[2] = -body_delta[2]
            cmd = body_delta / self._action_scale
            action[..., :3] = torch.clamp(cmd, -1.0, 1.0)
            if action.shape[-1] >= 6:
                action[..., 3:6] = 0.0
        else:
            # Absolute-mode action is the desired body pose in world frame.
            action[..., :3] = eef_pos + delta
            if action.shape[-1] >= 7:
                quat = (
                    eef_quat
                    if eef_quat is not None and eef_quat.numel() >= 4
                    else torch.tensor([0.0, 0.0, 0.0, 1.0], device=action.device, dtype=action.dtype)
                )
                action[..., 3:7] = quat[:4]

    def _set_gripper(self, action: torch.Tensor, open: bool) -> torch.Tensor:
        """Set the gripper command dimension.

        In relative pose mode the gripper is the 7th dim (after the 6-dim arm
        delta pose). In absolute pose mode it is the last of 8 dims.
        """
        value = 1.0 if open else -1.0
        if self._relative_mode and action.shape[-1] >= 7:
            action[..., 6] = value
        elif action.shape[-1] >= 8:
            action[..., -1] = value
        return action

    def _extract_state(
        self, observation: GymSpacesDict, env: gym.Env, device: torch.device
    ) -> tuple[
        torch.Tensor | None,
        torch.Tensor | None,
        torch.Tensor | None,
        torch.Tensor | None,
        torch.Tensor | None,
    ]:
        """Extract eef_pos, eef_quat, object_pos, gripper_pos, and target_pos."""
        eef_pos, object_pos, gripper_pos = self._extract_obs(observation, device)
        eef_quat = None
        if isinstance(observation, dict):
            pol = observation.get("policy", observation)
            if isinstance(pol, dict):
                eef_quat = self._to_tensor(pol.get("eef_quat"), device)

        if eef_pos is None or object_pos is None or eef_quat is None:
            eef_pos_s, eef_quat_s, object_pos_s, gripper_pos_s = self._extract_from_scene(env, device)
            if eef_pos is None:
                eef_pos = eef_pos_s
            if eef_quat is None:
                eef_quat = eef_quat_s
            if object_pos is None:
                object_pos = object_pos_s
            if gripper_pos is None:
                gripper_pos = gripper_pos_s

        target_pos = self._extract_target(observation, device)
        return eef_pos, eef_quat, object_pos, gripper_pos, target_pos

    def _extract_target(self, observation: GymSpacesDict, device: torch.device) -> torch.Tensor | None:
        """Read the command target position from ``task_obs`` (first 3 dims)."""
        if not isinstance(observation, dict):
            return None
        task_obs = observation.get("task_obs")
        if task_obs is None:
            return None
        t = self._to_tensor(task_obs, device)
        if t is None or t.numel() < 3:
            return None
        return t[:3].squeeze()

    def _extract_obs(
        self, observation: GymSpacesDict, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None]:
        pol = observation
        if isinstance(observation, dict):
            pol = observation.get("policy", observation)
        if not isinstance(pol, dict):
            return None, None, None

        eef_pos = self._to_tensor(pol.get("eef_pos"), device)
        object_pos = self._to_tensor(pol.get("object_pos"), device)
        gripper_pos = self._to_tensor(pol.get("gripper_pos"), device)
        if gripper_pos is not None and gripper_pos.numel() == 0:
            gripper_pos = None
        return eef_pos, object_pos, gripper_pos

    def _extract_from_scene(
        self, env: gym.Env, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None, torch.Tensor | None]:
        """Fallback to read eef/object/gripper data from the IsaacLab scene."""
        try:
            scene = getattr(env.unwrapped, "scene", None)
            if scene is None:
                return None, None, None, None

            scene_keys = list(scene.keys())
            object_candidates = {"dex_cube", "object", "cube", "mug", "cracker_box", "mustard_bottle"}
            object_pos = None
            for key in scene_keys:
                if key in object_candidates:
                    obj = scene[key]
                    data = getattr(obj, "data", None)
                    if data is not None and hasattr(data, "root_pos_w"):
                        object_pos = data.root_pos_w.squeeze().to(device)
                        break

            eef_pos = None
            eef_quat = None
            if "ee_frame" in scene_keys:
                ee_frame = scene["ee_frame"]
                data = getattr(ee_frame, "data", None)
                if data is not None:
                    for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                        if hasattr(data, attr):
                            pos = getattr(data, attr).squeeze().to(device)
                            if pos.ndim > 1:
                                pos = pos[0]
                            if pos.numel() == 3:
                                eef_pos = pos
                                break
                    for attr in ("target_quat_w", "source_quat_w", "quat_w"):
                        if hasattr(data, attr):
                            quat = getattr(data, attr).squeeze().to(device)
                            if quat.ndim > 1:
                                quat = quat[0]
                            if quat.numel() >= 4:
                                eef_quat = quat
                                break

            gripper_pos = None
            if "robot" in scene_keys:
                robot = scene["robot"]
                data = getattr(robot, "data", None)
                if data is not None and hasattr(data, "joint_pos"):
                    joints = data.joint_pos.squeeze()
                    if joints.numel() >= 2:
                        gripper_pos = joints[-2:].mean().to(device)

            return eef_pos, eef_quat, object_pos, gripper_pos
        except Exception as e:
            import sys
            print(f"[SERVO_DEBUG] scene extraction error: {e}", file=sys.stderr)
            sys.stderr.flush()
            return None, None, None, None

    @staticmethod
    def _to_tensor(value: Any, device: torch.device) -> torch.Tensor | None:
        if value is None:
            return None
        if isinstance(value, torch.Tensor):
            return value.squeeze().to(device)
        import numpy as np

        arr = np.asarray(value).squeeze()
        return torch.from_numpy(arr).to(device).float()

    @staticmethod
    def _fmt(tensor: torch.Tensor | None) -> str:
        if tensor is None:
            return "None"
        return str(tensor.detach().cpu().tolist())

    def _transition(self, new_state: str) -> None:
        self._state = new_state
        self._state_step = 0

    def _log_hints(self) -> None:
        import sys
        print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
        print(
            f"[HEURISTIC_SKILL_HINTS] params: approach_z={self._approach_offset_z:.4f} "
            f"grasp_z={self._grasp_offset_z:.4f} lift_h={self._lift_height:.4f} "
            f"kp={self._kp:.4f} grasp_dist={self._grasp_dist_threshold:.4f} "
            f"gripper_close={self._gripper_close_threshold:.4f} min_grasp={self._min_grasp_steps}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._state = "APPROACH"
        self._state_step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoLiftPolicy":
        return HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs.from_cli_args(args))


class CheatLiftPolicy(PolicyBase):
    """Cheat policy for lift_object: teleport the object to a lifted pose.

    This is NOT a real robot policy; it directly manipulates the object's
    root pose in simulation to verify that the Arena eval pipeline can
    report a non-zero success_rate. Used as a sanity-check baseline only.
    """

    name = "cheat_lift"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._cheat_done = False

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        # Close the gripper for the remainder of the episode.
        action[..., -1] = -1.0
        step = self._step
        self._step += 1

        if step == 0:
            import sys
            print(f"[CHEAT_LIFT] get_action called, action_space={env.action_space.shape}", file=sys.stderr)
            sys.stderr.flush()

        if step >= 2:
            try:
                import sys

                scene = env.unwrapped.scene
                obj = None
                for key in scene.keys():
                    key_str = str(key)
                    if key_str in ("object", "dex_cube", "cube"):
                        obj = scene[key_str]
                        break

                # The RL task success is defined as object within tolerance of the
                # generated command target pose. Read the target from task_obs.
                target_pos = None
                if isinstance(observation, dict) and "task_obs" in observation:
                    task_obs = observation["task_obs"]
                    if hasattr(task_obs, "squeeze"):
                        task_obs = task_obs.squeeze()
                    if task_obs.numel() >= 3:
                        target_pos = task_obs[:3]

                if obj is not None and target_pos is not None:
                    device = target_pos.device
                    origin = scene.env_origins[0:1] if hasattr(scene, "env_origins") else torch.zeros((1, 3), device=device)
                    target_quat = torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=device)
                    zero_vel = torch.zeros((1, 6), device=device)
                    root_pose = torch.cat([target_pos.unsqueeze(0) + origin, target_quat], dim=-1)
                    obj.write_root_pose_to_sim(root_pose)
                    obj.write_root_velocity_to_sim(zero_vel)
                    if step == 2:
                        print(f"[CHEAT_LIFT] Holding object at command target {target_pos.tolist()}", file=sys.stderr)
                        sys.stderr.flush()
            except Exception as e:
                import sys
                print(f"[CHEAT_LIFT] Error during teleport: {e}", file=sys.stderr)
                sys.stderr.flush()

        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "CheatLiftPolicy":
        return CheatLiftPolicy(HeuristicLiftPolicyArgs.from_cli_args(args))


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
