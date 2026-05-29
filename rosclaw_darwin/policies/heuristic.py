"""Generic approach-grasp-lift heuristic policy.

Works with any task where the observation contains `eef_pos` and `object_pos`.
Assumes absolute pose control (DifferentialIK with use_relative_mode=False).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch


@dataclass
class ApproachGraspLiftConfig:
    """Configuration for the heuristic policy."""

    approach_height: float = 0.20
    grasp_height: float = 0.10
    lift_height: float = 0.30
    place_height: float = 0.10
    place_offset_xyz: tuple[float, float, float] = (0.10, 0.0, 0.0)

    # Phase durations (number of steps)
    approach_steps: int = 30
    descend_steps: int = 20
    grip_steps: int = 15
    lift_steps: int = 20
    move_steps: int = 20
    lower_steps: int = 20
    release_steps: int = 10

    # Control gains
    kp_xy: float = 3.0
    kp_z: float = 2.0

    # Thresholds
    gripper_close_dist: float = 0.06
    gripper_open_value: float = 1.0
    gripper_close_value: float = -1.0


class ApproachGraspLiftPolicy:
    """Stateful heuristic policy that approaches, grasps, lifts, and places.

    The policy maintains an internal step counter and executes a phased
    open-loop + closed-loop trajectory:

        Phase 0: Approach   — move above object at approach_height
        Phase 1: Descend    — lower to grasp_height
        Phase 2: Grip       — close gripper
        Phase 3: Lift       — raise to lift_height
        Phase 4: Move       — translate by place_offset_xyz
        Phase 5: Lower      — descend to place_height
        Phase 6: Release    — open gripper
    """

    def __init__(
        self,
        action_shape: tuple[int, ...],
        device: str | torch.device = "cuda:0",
        config: ApproachGraspLiftConfig | None = None,
    ):
        self.action_shape = action_shape
        self.device = torch.device(device)
        self.config = config or ApproachGraspLiftConfig()
        self._step = 0
        self._init_quat: torch.Tensor | None = None

    def __call__(self, obs: dict[str, Any]) -> dict[str, float]:
        """Compute action for current observation."""
        self._step += 1
        cfg = self.config

        # Extract positions from standardized observation
        eef_pos = self._extract_pos(obs.get("eef_pos"))
        obj_pos = self._extract_pos(obs.get("object_pos"))

        # Cache initial quaternion on first call for orientation stability
        eef_quat = obs.get("eef_quat")
        if eef_quat is not None and self._init_quat is None:
            self._init_quat = self._extract_pos(eef_quat)

        # Default: hover above table, gripper open
        if obj_pos is None:
            return {
                "x": 0.35,
                "y": 0.0,
                "z": cfg.approach_height,
                "qw": 1.0,
                "qx": 0.0,
                "qy": 0.0,
                "qz": 0.0,
                "gripper": cfg.gripper_open_value,
            }

        obj_x, obj_y, obj_z = float(obj_pos[0]), float(obj_pos[1]), float(obj_pos[2])

        # Phase durations
        p0 = cfg.approach_steps
        p1 = p0 + cfg.descend_steps
        p2 = p1 + cfg.grip_steps
        p3 = p2 + cfg.lift_steps
        p4 = p3 + cfg.move_steps
        p5 = p4 + cfg.lower_steps

        step = self._step

        # Phase 0: Approach — move to above object
        if step <= p0:
            target_x = obj_x
            target_y = obj_y
            target_z = cfg.approach_height
            gripper = cfg.gripper_open_value

        # Phase 1: Descend — lower to grasp height
        elif step <= p1:
            target_x = obj_x
            target_y = obj_y
            target_z = cfg.grasp_height
            gripper = cfg.gripper_open_value

        # Phase 2: Grip — close gripper
        elif step <= p2:
            target_x = obj_x
            target_y = obj_y
            target_z = cfg.grasp_height
            gripper = cfg.gripper_close_value

        # Phase 3: Lift — raise with object
        elif step <= p3:
            target_x = obj_x
            target_y = obj_y
            target_z = cfg.lift_height
            gripper = cfg.gripper_close_value

        # Phase 4: Move — translate to place location
        elif step <= p4:
            target_x = obj_x + cfg.place_offset_xyz[0]
            target_y = obj_y + cfg.place_offset_xyz[1]
            target_z = cfg.lift_height + cfg.place_offset_xyz[2]
            gripper = cfg.gripper_close_value

        # Phase 5: Lower — descend at place location
        elif step <= p5:
            target_x = obj_x + cfg.place_offset_xyz[0]
            target_y = obj_y + cfg.place_offset_xyz[1]
            target_z = cfg.place_height
            gripper = cfg.gripper_close_value

        # Phase 6: Release — open gripper
        else:
            target_x = obj_x + cfg.place_offset_xyz[0]
            target_y = obj_y + cfg.place_offset_xyz[1]
            target_z = cfg.place_height
            gripper = cfg.gripper_open_value

        action: dict[str, float] = {
            "x": target_x,
            "y": target_y,
            "z": target_z,
            "gripper": gripper,
        }

        # Add orientation if we have initial quaternion
        if self._init_quat is not None and len(self._init_quat) >= 4:
            action["qw"] = float(self._init_quat[0])
            action["qx"] = float(self._init_quat[1])
            action["qy"] = float(self._init_quat[2])
            action["qz"] = float(self._init_quat[3])
        else:
            action["qw"] = 1.0
            action["qx"] = 0.0
            action["qy"] = 0.0
            action["qz"] = 0.0

        return action

    @staticmethod
    def _extract_pos(tensor: Any) -> torch.Tensor | None:
        """Extract a 1-D position tensor from possibly batched input."""
        if tensor is None:
            return None
        if hasattr(tensor, "dim") and tensor.dim() > 1:
            return tensor[0]
        return tensor
