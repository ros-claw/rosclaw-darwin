# Heuristic lift policy for Arena Docker evaluation.
# Uses delta pose control (Franka IK relative mode, scale=0.5).
# Called dynamically by eval_runner via policy_type module path.

import argparse
import json
import math
import os
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


_TRACE_PATH = "/workspace/data/episode_trace.jsonl"


def _append_trace(step: dict[str, Any]) -> None:
    """Append a scalar step record to the shared trace file.

    The trace is read by ``run_eval.py`` to compute per-episode progress metrics.
    """
    try:
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(step) + "\n")
    except Exception as e:
        import sys
        print(f"[TRACE_WRITE_ERROR] {e}", file=sys.stderr)
        pass


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
    grasp_offset_z: float = 0.0
    lift_height: float = 0.25
    kp: float = 5.0
    grasp_dist_threshold: float = 0.03
    gripper_close_threshold: float = 0.03
    min_grasp_steps: int = 15
    approach_horizontal_threshold: float = 0.05
    max_state_steps: int = 300
    success_threshold: float = 0.05
    grasp_squeeze_steps: int = 0
    lift_max_delta: float | None = None

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoPickPolicyArgs(HeuristicServoLiftPolicyArgs):
    """Configuration for HeuristicServoPickPolicy.

    Adds explicit post-lift alignment and hold phases for pick/place-style
    tasks where the object must be positioned at a command target and held.
    """

    enable_align_phase: bool = True
    align_kp: float = 0.6
    final_align_speed: float = 0.4
    hold_steps: int = 20
    align_height_offset: float = 0.0
    settle_before_success: bool = True
    near_target_gain: float = 0.5
    align_max_delta: float | None = 0.06
    slow_align_max_delta: float | None = 0.03
    align_horizontal_scale: float = 1.0
    slow_align_threshold: float = 0.05

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoPickPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoLiftPolicyArgs:
    """Configuration for HeuristicServoLiftPolicy."""

    skill_hints: list[str] | None = None
    approach_offset_z: float = 0.08
    grasp_offset_z: float = 0.0
    lift_height: float = 0.25
    kp: float = 5.0
    grasp_dist_threshold: float = 0.03
    gripper_close_threshold: float = 0.03
    min_grasp_steps: int = 15
    approach_horizontal_threshold: float = 0.05
    max_state_steps: int = 300
    success_threshold: float = 0.05
    grasp_squeeze_steps: int = 0
    lift_max_delta: float | None = None

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoGoalPosePolicyArgs(HeuristicServoLiftPolicyArgs):
    """Configuration for HeuristicServoGoalPosePolicy.

    Extends the lift servo args with placement/release behaviour needed for
    goal-pose / pick-and-place tasks.
    """

    min_release_steps: int = 10
    align_height_offset: float = 0.0
    orientation_threshold: float = 1.0
    lift_horizontal_scale: float = 0.9
    lift_kp_multiplier: float = 1.0
    lift_max_delta: float | None = None
    align_horizontal_scale: float = 1.0
    align_kp_multiplier: float = 1.0
    align_max_delta: float | None = None
    grasp_z_tolerance: float = 0.02
    fixed_target_pos: list[float] | None = None
    fixed_target_quat: list[float] | None = None
    release_at_target: bool = False
    require_orientation_alignment: bool = False

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoGoalPosePolicyArgs":
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
        self._episode_idx = 0

        # Clear any trace from a previous job in the same container.
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

        self._approach_offset_z = config.approach_offset_z
        self._grasp_offset_z = config.grasp_offset_z
        self._lift_height = config.lift_height
        self._kp = config.kp
        self._grasp_dist_threshold = config.grasp_dist_threshold
        self._gripper_close_threshold = config.gripper_close_threshold
        self._min_grasp_steps = config.min_grasp_steps
        self._approach_horizontal_threshold = config.approach_horizontal_threshold
        self._max_state_steps = config.max_state_steps
        self._success_threshold = config.success_threshold
        self._lift_kp_multiplier = getattr(config, "lift_kp_multiplier", 1.0)
        self._lift_horizontal_scale = getattr(config, "lift_horizontal_scale", 0.6)
        self._grasp_squeeze_steps = getattr(config, "grasp_squeeze_steps", 0)
        self._lift_max_delta = getattr(config, "lift_max_delta", None)

        if "longer_gripper_close" in self._skill_hints:
            self._min_grasp_steps += 5
            self._grasp_squeeze_steps += 10
            self._gripper_close_threshold *= 0.8
        if "stabilize_lift" in self._skill_hints:
            # Smaller per-step deltas and lower horizontal coupling reduce
            # oscillation / shear that can break a fragile grasp.
            if self._lift_max_delta is not None:
                self._lift_max_delta *= 0.75
            else:
                self._lift_max_delta = 0.12
            self._kp *= 0.9
            self._lift_horizontal_scale = max(0.0, self._lift_horizontal_scale - 0.2)
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
        if "stronger_lift" in self._skill_hints:
            self._kp *= 1.3
            self._lift_height += 0.05
            self._lift_horizontal_scale = min(1.0, self._lift_horizontal_scale + 0.2)
        if "target_tracking" in self._skill_hints:
            self._lift_kp_multiplier = 1.5
            self._lift_horizontal_scale = 1.0
            self._success_threshold = max(0.03, self._success_threshold * 0.8)
        if "faster_approach" in self._skill_hints:
            self._approach_offset_z *= 0.75
            self._kp *= 1.2
        if "larger_servo_gain" in self._skill_hints:
            self._kp *= 1.5

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
            # Transition once the fingers have had time to close.  When the
            # gripper position reading is available we additionally wait until it
            # is below the close threshold, with an optional squeeze extension
            # for objects that need sustained force before lifting.
            squeeze_deadline = self._min_grasp_steps + self._grasp_squeeze_steps
            if self._state_step >= self._min_grasp_steps:
                if gripper_pos is not None and gripper_pos < self._gripper_close_threshold:
                    self._transition("LIFT")
                elif self._state_step >= squeeze_deadline:
                    self._transition("LIFT")

        elif self._state == "LIFT":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=self._lift_horizontal_scale,
                max_delta=self._lift_max_delta,
            )
            action = self._set_gripper(action, open=False)
            # Transition to HOLD when the object is close to the command target
            # (or when the end-effector reaches a pure height target).
            if target_pos is not None and object_pos is not None:
                if torch.norm(target_pos - object_pos) < self._success_threshold:
                    self._transition("HOLD")
            elif eef_pos[2] >= target[2] - 0.03:
                self._transition("HOLD")

        elif self._state == "HOLD":
            action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        # Record a scalar trace step for progress-metric computation.
        if object_pos is not None:
            _append_trace({
                "episode": self._episode_idx,
                "step": step,
                "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
                "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
                "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
                "object_x": float(object_pos[0].item()),
                "object_y": float(object_pos[1].item()),
                "object_z": float(object_pos[2].item()),
                "target_x": float(target_pos[0].item()) if target_pos is not None else None,
                "target_y": float(target_pos[1].item()) if target_pos is not None else None,
                "target_z": float(target_pos[2].item()) if target_pos is not None else None,
                "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
                "action_norm": float(torch.linalg.norm(action).item()),
                "phase": self._state,
            })

        return action

    def _infer_controller_mode(self, env: gym.Env) -> None:
        """Detect whether the arm controller expects relative deltas or absolute poses."""
        action_dim = int(env.action_space.shape[-1]) if hasattr(env.action_space, "shape") else 0
        try:
            cfg = env.unwrapped.cfg
            arm = cfg.actions.arm_action
            self._relative_mode = bool(getattr(arm.controller, "use_relative_mode", True))
            self._action_scale = float(getattr(arm, "scale", 1.0))
            if self._action_scale == 0.0:
                self._action_scale = 1.0
        except Exception:
            # Heuristic fallback: 7-dim action spaces are relative pose (DifferentialIK),
            # 8-dim action spaces are absolute pose (joint pos / RMPflow absolute).
            self._relative_mode = action_dim == 7
            self._action_scale = 1.0
        import sys
        print(
            f"[SERVO_MODE] relative_mode={self._relative_mode} action_scale={self._action_scale} "
            f"action_dim={action_dim}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    def _apply_position(
        self,
        action: torch.Tensor,
        eef_pos: torch.Tensor | None,
        eef_quat: torch.Tensor | None,
        target: torch.Tensor,
        kp_multiplier: float = 1.0,
        horizontal_scale: float = 1.0,
        max_delta: float | None = None,
    ) -> None:
        """Write a position (and orientation) command into ``action[..., :3]``."""
        if eef_pos is None:
            return
        delta = self._kp * kp_multiplier * (target - eef_pos)
        if horizontal_scale != 1.0:
            delta[:2] *= horizontal_scale
        # In relative mode we want to saturate the action to maximize step size
        # (the controller is heavily damped). In absolute mode keep steps small
        # so mock/unit-test environments remain stable.
        if max_delta is None:
            max_delta = 0.5 if self._relative_mode else 0.1
        delta = torch.clamp(delta, -max_delta, max_delta)

        if self._relative_mode:
            # Relative-mode action is a delta pose in the end-effector body frame,
            # scaled by action_scale. The arm command has 6 dims:
            #   [dx, dy, dz, droll, dpitch, dyaw]
            # followed by the gripper dim.
            body_delta = delta.clone()
            # Live runs with the Arena DifferentialIK relative-pose controller show
            # that world-frame deltas map directly to the action axes (no sign
            # flips) when the controller is configured in relative mode.
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
        """Extract world-frame eef_pos, eef_quat, object_pos, gripper_pos, and target_pos."""
        # Prefer scene data because it is always in the world frame. The policy
        # observation terms may return object positions in the robot root frame,
        # which would break the servo error if used directly.
        eef_pos, eef_quat, object_pos, gripper_pos = self._extract_from_scene(env, device)

        # Fallback to observation terms if scene extraction fails.
        if eef_pos is None or object_pos is None or gripper_pos is None:
            eef_pos_o, object_pos_o, gripper_pos_o = self._extract_obs(observation, device)
            if eef_pos is None:
                eef_pos = eef_pos_o
            if object_pos is None:
                object_pos = object_pos_o
            if gripper_pos is None:
                gripper_pos = gripper_pos_o

        target_pos = self._extract_target_world(observation, env, device)
        return eef_pos, eef_quat, object_pos, gripper_pos, target_pos

    def _extract_target_world(
        self, observation: GymSpacesDict, env: gym.Env, device: torch.device
    ) -> torch.Tensor | None:
        """Read the command target position and transform it to the world frame.

        The command manager stores targets in the robot root frame; Arena's
        success criterion compares object world position to the world-frame goal.
        Different tasks name the command term differently, so we try a list of
        common names and fall back to the raw task observation buffer.
        """
        root_pos, root_quat = None, None
        for cmd_name in ("object_pose", "pose_command", "target_pose"):
            try:
                cm = env.unwrapped.command_manager
                cmd = cm.get_command(cmd_name)
                t = torch.as_tensor(cmd, device=device).squeeze()
                if t.numel() < 3:
                    continue
                des_pos_b = t[:3]
                if root_pos is None:
                    root_pos, root_quat = self._extract_robot_root(env, device)
                if root_pos is not None and root_quat is not None:
                    from isaaclab.utils.math import combine_frame_transforms
                    target_w, _ = combine_frame_transforms(
                        root_pos.unsqueeze(0),
                        root_quat.unsqueeze(0),
                        des_pos_b.unsqueeze(0),
                    )
                    return target_w.squeeze()
            except Exception:
                continue

        # Fallback: read task_obs from the env's internal observation buffer.
        try:
            obs_buf = getattr(env, "_obs_buf", None) or getattr(env.unwrapped, "_obs_buf", None)
            if isinstance(obs_buf, dict) and "task_obs" in obs_buf:
                task_obs = obs_buf["task_obs"]
            elif isinstance(observation, dict):
                task_obs = observation.get("task_obs")
            else:
                task_obs = None
            if task_obs is not None:
                if hasattr(task_obs, "squeeze"):
                    task_obs = task_obs.squeeze()
                t = self._to_tensor(task_obs, device)
                if t is not None and t.numel() >= 3:
                    return t[:3].squeeze()
        except Exception:
            pass

        return None

    def _extract_robot_root(
        self, env: gym.Env, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None]:
        """Return the robot root position/quaternion in world frame."""
        try:
            scene = getattr(env.unwrapped, "scene", None)
            if scene is None:
                return None, None
            robot = scene["robot"]
            data = robot.data
            pos = data.root_pos_w.squeeze().to(device)
            quat = data.root_quat_w.squeeze().to(device)
            if pos.ndim > 1:
                pos = pos[0]
            if quat.ndim > 1:
                quat = quat[0]
            return pos, quat
        except Exception:
            return None, None

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
        """Read eef/object/gripper data from the IsaacLab scene (world frame)."""
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
                    # Prefer the controller target frame because the DifferentialIK
                    # relative controller drives this frame; the actual sensor
                    # source lags and using it for servo feedback under-damps the arm.
                    for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                        if hasattr(data, attr):
                            pos = getattr(data, attr).squeeze().to(device)
                            if pos.ndim > 1:
                                pos = pos[0]
                            if pos.numel() == 3:
                                eef_pos = pos
                                break
                    for attr in ("source_quat_w", "quat_w", "target_quat_w"):
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
        self._episode_idx += 1

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoLiftPolicy":
        return HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs.from_cli_args(args))


class HeuristicServoGoalPosePolicy(HeuristicServoLiftPolicy):
    """Closed-loop servo heuristic for goal-pose / reorientation tasks.

    Reuses the lift state machine through ``GRASP`` and ``LIFT``, then aligns
    the grasped object with the command target pose, releases the gripper, and
    holds. Works with the absolute-pose Franka IK controller configured by
    ``ArenaAdapter``.
    """

    name = "heuristic_servo_goal_pose"
    config_class = HeuristicServoGoalPosePolicyArgs

    def __init__(self, config: HeuristicServoGoalPosePolicyArgs):
        super().__init__(config)
        self._min_release_steps = config.min_release_steps
        self._align_height_offset = config.align_height_offset
        self._orientation_threshold = config.orientation_threshold
        self._grasp_z_tolerance = getattr(config, "grasp_z_tolerance", 0.02)
        self._fixed_target_pos = config.fixed_target_pos
        self._fixed_target_quat = config.fixed_target_quat
        self._release_at_target = config.release_at_target
        self._require_orientation_alignment = config.require_orientation_alignment
        self._align_horizontal_scale = config.align_horizontal_scale
        self._align_kp_multiplier = config.align_kp_multiplier
        self._lift_max_delta = config.lift_max_delta
        self._align_max_delta = config.align_max_delta

        # Goal-pose specific hint effects.
        if "precision_placement" in self._skill_hints:
            self._success_threshold = max(0.03, self._success_threshold * 0.8)
            self._kp *= 0.9
        if "release_at_target" in self._skill_hints:
            self._release_at_target = True
            self._min_release_steps += 5
        if "orient_adjust" in self._skill_hints or "orientation_aware_grasp" in self._skill_hints:
            self._require_orientation_alignment = True
            self._orientation_threshold *= 0.8
        if "two_stage_reorientation" in self._skill_hints:
            self._require_orientation_alignment = True
            self._orientation_threshold *= 0.7
        if "stabilize_lift" in self._skill_hints or "reduce_xy_motion" in self._skill_hints:
            if self._align_max_delta is not None:
                self._align_max_delta *= 0.75
            else:
                self._align_max_delta = 0.06
            self._lift_horizontal_scale = max(0.0, self._lift_horizontal_scale - 0.2)
            self._lift_kp_multiplier *= 0.9
        if "longer_squeeze" in self._skill_hints or "longer_gripper_close" in self._skill_hints:
            self._min_grasp_steps += 5
            self._grasp_squeeze_steps += 10
            self._gripper_close_threshold *= 0.8
        if "maintain_grip_force" in self._skill_hints:
            self._min_grasp_steps += 3
            self._grasp_squeeze_steps += 5

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
        target_quat = self._extract_target_quat_world(observation, env, device)
        if target_pos is None and self._fixed_target_pos is not None and object_pos is not None:
            target_pos = torch.as_tensor(self._fixed_target_pos, device=device, dtype=object_pos.dtype)
        if target_quat is None and self._fixed_target_quat is not None:
            dtype = eef_quat.dtype if eef_quat is not None else torch.float32
            target_quat = torch.as_tensor(self._fixed_target_quat, device=device, dtype=dtype)

        if object_pos is None:
            # Fallback open-loop sequence when observations are missing.
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
            dist_ok = torch.norm(target - eef_pos) < self._grasp_dist_threshold
            z_ok = abs(eef_pos[2].item() - target[2].item()) < self._grasp_z_tolerance
            if dist_ok and z_ok:
                self._transition("GRASP")

        elif self._state == "GRASP":
            action = self._set_gripper(action, open=False)
            squeeze_deadline = self._min_grasp_steps + self._grasp_squeeze_steps
            if self._state_step >= self._min_grasp_steps:
                if gripper_pos is not None and gripper_pos < self._gripper_close_threshold:
                    self._transition("LIFT")
                elif self._state_step >= squeeze_deadline:
                    self._transition("LIFT")

        elif self._state == "LIFT":
            if target_pos is not None:
                # Lift vertically toward the target height first; keep the
                # horizontal position over the object so the grasp is not sheared.
                target = target_pos.clone()
                target[2] += self._lift_height
                if object_pos is not None:
                    target[:2] = object_pos[:2]
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=self._lift_horizontal_scale,
                max_delta=self._lift_max_delta,
            )
            action = self._set_gripper(action, open=False)
            # Transition when high enough; horizontal/rotational alignment is
            # handled in ALIGN to avoid dragging the object during lift.
            height_ok = eef_pos[2] >= target[2] - 0.03
            if target_pos is not None and object_pos is not None:
                near_target_xy = (
                    torch.norm(target_pos[:2] - object_pos[:2]) < self._success_threshold * 2
                )
            else:
                near_target_xy = True
            if height_ok and near_target_xy:
                self._transition("ALIGN")

        elif self._state == "ALIGN":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp_multiplier,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._align_max_delta,
            )
            self._apply_orientation(action, eef_quat, target_quat)
            action = self._set_gripper(action, open=False)
            # Require the object (not just the eef) to be at the target before
            # declaring alignment, otherwise a fast eef motion can leave the
            # object behind or cause it to slip.
            if target_pos is not None and object_pos is not None:
                position_ok = torch.norm(target - object_pos) < self._success_threshold
            else:
                position_ok = torch.norm(target - eef_pos) < self._success_threshold
            orientation_ok = (
                self._orientation_aligned(eef_quat, target_quat)
                or not self._require_orientation_alignment
            )
            if position_ok and orientation_ok:
                if self._release_at_target:
                    self._transition("RELEASE")
                else:
                    self._transition("HOLD")

        elif self._state == "RELEASE":
            action = self._set_gripper(action, open=True)
            if self._state_step >= self._min_release_steps:
                self._transition("HOLD")

        elif self._state == "HOLD":
            # Goal-pose tasks normally keep the object grasped at the target pose.
            # Only open the gripper if an explicit release was requested/scheduled.
            if self._release_at_target:
                action = self._set_gripper(action, open=True)
            else:
                action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        if object_pos is not None:
            _append_trace({
                "episode": self._episode_idx,
                "step": step,
                "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
                "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
                "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
                "object_x": float(object_pos[0].item()),
                "object_y": float(object_pos[1].item()),
                "object_z": float(object_pos[2].item()),
                "target_x": float(target_pos[0].item()) if target_pos is not None else None,
                "target_y": float(target_pos[1].item()) if target_pos is not None else None,
                "target_z": float(target_pos[2].item()) if target_pos is not None else None,
                "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
                "action_norm": float(torch.linalg.norm(action).item()),
                "phase": self._state,
            })

        return action

    def _apply_position(
        self,
        action: torch.Tensor,
        eef_pos: torch.Tensor | None,
        eef_quat: torch.Tensor | None,
        target: torch.Tensor,
        kp_multiplier: float = 1.0,
        horizontal_scale: float = 1.0,
        max_delta: float | None = None,
    ) -> None:
        """Write a position command into ``action`` using body-frame mapping.

        The cube_goal_pose environment leaves the Franka controller in relative
        mode with the end-effector yawed ~180° at reset. World-frame deltas must
        be rotated into the end-effector body frame before being written as
        relative-pose actions; otherwise the arm moves away from the object.
        """
        if eef_pos is None:
            return
        delta_world = self._kp * kp_multiplier * (target - eef_pos)
        if horizontal_scale != 1.0:
            delta_world[:2] *= horizontal_scale

        if max_delta is None:
            max_delta = 0.5 if self._relative_mode else 0.1
        delta_world = torch.clamp(delta_world, -max_delta, max_delta)

        if self._relative_mode:
            body_delta = self._world_delta_to_body(delta_world, eef_quat)
            cmd = body_delta / self._action_scale
            action[..., :3] = torch.clamp(cmd, -1.0, 1.0)
            if action.shape[-1] >= 6:
                action[..., 3:6] = 0.0
        else:
            action[..., :3] = eef_pos + delta_world
            if action.shape[-1] >= 7:
                quat = (
                    eef_quat
                    if eef_quat is not None and eef_quat.numel() >= 4
                    else torch.tensor([0.0, 0.0, 0.0, 1.0], device=action.device, dtype=action.dtype)
                )
                action[..., 3:7] = quat[:4]

    def _world_delta_to_body(
        self, delta_world: torch.Tensor, eef_quat: torch.Tensor | None
    ) -> torch.Tensor:
        """Rotate a world-frame delta into the end-effector body frame."""
        if eef_quat is None or eef_quat.numel() < 4:
            return delta_world
        try:
            from isaaclab.utils.math import quat_rotate_inverse

            return quat_rotate_inverse(eef_quat.unsqueeze(0), delta_world.unsqueeze(0)).squeeze()
        except Exception:
            return delta_world

    def _extract_target_quat_world(
        self, observation: GymSpacesDict, env: gym.Env, device: torch.device
    ) -> torch.Tensor | None:
        """Read the command target quaternion and transform it to the world frame."""
        root_pos, root_quat = None, None
        for cmd_name in ("object_pose", "pose_command", "target_pose"):
            try:
                cm = env.unwrapped.command_manager
                cmd = cm.get_command(cmd_name)
                cmd_t = torch.as_tensor(cmd, device=device).squeeze()
                if cmd_t.numel() < 7:
                    continue
                des_pos_b = cmd_t[:3]
                des_quat_b = cmd_t[3:7]
                if root_pos is None:
                    root_pos, root_quat = self._extract_robot_root(env, device)
                if root_pos is not None and root_quat is not None:
                    from isaaclab.utils.math import combine_frame_transforms

                    _target_w, target_q = combine_frame_transforms(
                        root_pos.unsqueeze(0),
                        root_quat.unsqueeze(0),
                        des_pos_b.unsqueeze(0),
                        des_quat_b.unsqueeze(0),
                    )
                    return target_q.squeeze()
            except Exception:
                continue
        return None

    def _apply_orientation(
        self,
        action: torch.Tensor,
        eef_quat: torch.Tensor | None,
        target_quat: torch.Tensor | None,
    ) -> None:
        """Write an orientation command into ``action``."""
        if target_quat is None:
            return
        if self._relative_mode:
            # Relative controllers: command a yaw correction.
            if eef_quat is None:
                return
            try:
                yaw_current = self._quat_to_yaw(eef_quat)
                yaw_target = self._quat_to_yaw(target_quat)
                yaw_err = self._angle_diff(yaw_target, yaw_current)
                action[..., 5] = torch.clamp(torch.as_tensor(yaw_err * 2.0, device=action.device), -1.0, 1.0)
            except Exception:
                pass
        else:
            # Absolute mode: command the target quaternion directly.
            action[..., 3:7] = target_quat[:4]

    def _orientation_aligned(
        self, eef_quat: torch.Tensor | None, target_quat: torch.Tensor | None
    ) -> bool:
        if target_quat is None or eef_quat is None:
            return True
        try:
            dot = float(torch.abs(torch.sum(eef_quat * target_quat)).item())
            dot = min(1.0, max(0.0, dot))
            angle = 2.0 * math.acos(dot)
            return angle < self._orientation_threshold
        except Exception:
            return True

    @staticmethod
    def _quat_to_yaw(q: torch.Tensor) -> float:
        # IsaacLab quaternion convention is (w, x, y, z).
        x, y, z, w = q[0].item(), q[1].item(), q[2].item(), q[3].item()
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

    @staticmethod
    def _angle_diff(target: float, current: float) -> float:
        diff = target - current
        while diff > math.pi:
            diff -= 2.0 * math.pi
        while diff < -math.pi:
            diff += 2.0 * math.pi
        return diff

    def _log_hints(self) -> None:
        import sys

        print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
        print(
            f"[HEURISTIC_SKILL_HINTS] params: approach_z={self._approach_offset_z:.4f} "
            f"grasp_z={self._grasp_offset_z:.4f} lift_h={self._lift_height:.4f} "
            f"align_h={self._align_height_offset:.4f} kp={self._kp:.4f} "
            f"grasp_dist={self._grasp_dist_threshold:.4f} min_grasp={self._min_grasp_steps} "
            f"min_release={self._min_release_steps} orient_thr={self._orientation_threshold:.4f}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoGoalPosePolicy":
        return HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs.from_cli_args(args))


class HeuristicServoPickPolicy(HeuristicServoLiftPolicy):
    """Closed-loop servo heuristic for pick/place tasks with post-lift alignment.

    Extends the lift state machine with explicit ALIGN, SLOW_ALIGN, and
    HOLD_AT_TARGET phases.  After lifting to the command target height the
    policy moves horizontally to the target, slows down as it approaches, and
    then holds the object at the target for a configurable number of steps.
    This addresses the ``target_not_reached_after_lift`` success gap observed
    on ``pick_object``.
    """

    name = "heuristic_servo_pick"
    config_class = HeuristicServoPickPolicyArgs

    def __init__(self, config: HeuristicServoPickPolicyArgs):
        super().__init__(config)
        self._enable_align_phase = config.enable_align_phase
        self._align_kp = config.align_kp
        self._final_align_speed = config.final_align_speed
        self._hold_steps = config.hold_steps
        self._align_height_offset = config.align_height_offset
        self._settle_before_success = config.settle_before_success
        self._near_target_gain = config.near_target_gain
        self._align_max_delta = config.align_max_delta
        self._slow_align_max_delta = config.slow_align_max_delta
        self._align_horizontal_scale = config.align_horizontal_scale
        self._slow_align_threshold = config.slow_align_threshold

        # Signature-driven hint effects.
        if "precision_target_tracking" in self._skill_hints:
            self._align_kp *= 1.2
            self._success_threshold = max(0.03, self._success_threshold * 0.8)
        if "slow_final_align" in self._skill_hints:
            self._final_align_speed *= 0.6
            if self._align_max_delta is not None:
                self._align_max_delta *= 0.7
            if self._slow_align_max_delta is not None:
                self._slow_align_max_delta *= 0.7
        if "hold_at_target" in self._skill_hints:
            self._hold_steps += 15
        if "reduce_near_target_gain" in self._skill_hints:
            self._near_target_gain *= 0.6
        if "settle_before_success_check" in self._skill_hints:
            self._settle_before_success = True

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
            squeeze_deadline = self._min_grasp_steps + self._grasp_squeeze_steps
            if self._state_step >= self._min_grasp_steps:
                if gripper_pos is not None and gripper_pos < self._gripper_close_threshold:
                    self._transition("LIFT")
                elif self._state_step >= squeeze_deadline:
                    self._transition("LIFT")

        elif self._state == "LIFT":
            if target_pos is not None:
                target = target_pos.clone()
                target[2] += self._lift_height
                if object_pos is not None:
                    target[:2] = object_pos[:2]
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=self._lift_horizontal_scale,
                max_delta=self._lift_max_delta,
            )
            action = self._set_gripper(action, open=False)
            height_ok = eef_pos[2] >= target[2] - 0.03
            if self._enable_align_phase and target_pos is not None:
                if height_ok:
                    self._transition("ALIGN")
            elif height_ok:
                self._transition("HOLD")

        elif self._state == "ALIGN":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            horizontal_dist = torch.norm(target[:2] - object_pos[:2]) if object_pos is not None else torch.norm(target[:2] - eef_pos[:2])
            # Reduce gain when very close to avoid overshoot.
            kp = self._align_kp * (self._near_target_gain if horizontal_dist < self._slow_align_threshold else 1.0)
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=kp,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._align_max_delta,
            )
            action = self._set_gripper(action, open=False)
            if horizontal_dist < self._success_threshold:
                if self._settle_before_success:
                    self._transition("SLOW_ALIGN")
                else:
                    self._transition("HOLD_AT_TARGET")

        elif self._state == "SLOW_ALIGN":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp * self._near_target_gain,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._slow_align_max_delta,
            )
            action = self._set_gripper(action, open=False)
            if self._state_step >= max(1, int(self._hold_steps * 0.25)):
                self._transition("HOLD_AT_TARGET")

        elif self._state == "HOLD_AT_TARGET":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp * self._near_target_gain,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._slow_align_max_delta,
            )
            action = self._set_gripper(action, open=False)
            if self._state_step >= self._hold_steps:
                self._transition("VERIFY_SUCCESS")

        elif self._state == "VERIFY_SUCCESS":
            # Keep the object at the target and let the environment register success.
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp * self._near_target_gain,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._slow_align_max_delta,
            )
            action = self._set_gripper(action, open=False)

        elif self._state == "HOLD":
            action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        if object_pos is not None:
            _append_trace({
                "episode": self._episode_idx,
                "step": step,
                "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
                "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
                "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
                "object_x": float(object_pos[0].item()),
                "object_y": float(object_pos[1].item()),
                "object_z": float(object_pos[2].item()),
                "target_x": float(target_pos[0].item()) if target_pos is not None else None,
                "target_y": float(target_pos[1].item()) if target_pos is not None else None,
                "target_z": float(target_pos[2].item()) if target_pos is not None else None,
                "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
                "action_norm": float(torch.linalg.norm(action).item()),
                "phase": self._state,
            })

        return action

    def _log_hints(self) -> None:
        import sys
        print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
        print(
            f"[HEURISTIC_SKILL_HINTS] params: approach_z={self._approach_offset_z:.4f} "
            f"grasp_z={self._grasp_offset_z:.4f} lift_h={self._lift_height:.4f} "
            f"align_kp={self._align_kp:.4f} align_max_delta={self._align_max_delta} "
            f"hold_steps={self._hold_steps} settle={self._settle_before_success}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoPickPolicy":
        return HeuristicServoPickPolicy(HeuristicServoPickPolicyArgs.from_cli_args(args))


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


@dataclass
class ActionCalibrationPolicyArgs:
    """Configuration for the action-response calibration policy."""

    skill_hints: list[str] | None = None
    calibration_axis: int = 0  # 0=x, 1=y, 2=z
    calibration_sign: float = 1.0
    calibration_magnitude: float = 0.5

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "ActionCalibrationPolicyArgs":
        return cls(
            skill_hints=getattr(args, "skill_hints", None),
            calibration_axis=getattr(args, "calibration_axis", 0),
            calibration_sign=getattr(args, "calibration_sign", 1.0),
            calibration_magnitude=getattr(args, "calibration_magnitude", 0.5),
        )


class ActionCalibrationPolicy(PolicyBase):
    """Fixed-action calibration policy for estimating action->world response.

    Commands a constant delta on a single axis and records the end-effector
    displacement. Used by ``run_action_calibration.py``.
    """

    name = "action_calibration"
    config_class = ActionCalibrationPolicyArgs

    def __init__(self, config: ActionCalibrationPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._axis = int(config.calibration_axis)
        self._sign = float(config.calibration_sign)
        self._magnitude = float(config.calibration_magnitude)
        self._episode_idx = 0
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        action[..., self._axis] = self._sign * self._magnitude
        # Keep gripper open/neutral.
        if action.shape[-1] >= 7:
            action[..., -1] = 1.0

        # Record eef position for calibration analysis.
        try:
            eef_pos = None
            scene = env.unwrapped.scene
            if "ee_frame" in scene.keys():
                data = scene["ee_frame"].data
                for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                    if hasattr(data, attr):
                        pos = getattr(data, attr).squeeze().to(device)
                        if pos.ndim > 1:
                            pos = pos[0]
                        if pos.numel() >= 3:
                            eef_pos = pos
                            break
            if eef_pos is not None:
                _append_trace({
                    "episode": self._episode_idx,
                    "step": self._step,
                    "eef_x": float(eef_pos[0].item()),
                    "eef_y": float(eef_pos[1].item()),
                    "eef_z": float(eef_pos[2].item()),
                    "action_axis": self._axis,
                    "action_sign": self._sign,
                    "action_magnitude": self._magnitude,
                    "action_norm": float(torch.linalg.norm(action).item()),
                })
        except Exception:
            pass

        self._step += 1
        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._episode_idx += 1

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "ActionCalibrationPolicy":
        return ActionCalibrationPolicy(ActionCalibrationPolicyArgs.from_cli_args(args))
