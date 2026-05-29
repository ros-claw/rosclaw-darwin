"""Example external policy for ROSClaw-Darwin.

Demonstrates how to write a custom policy that can be loaded via:

    python run_eval.py --policy-module examples/external_policy.py:proportional_controller

The policy function receives standardized observations and returns actions.
"""

from __future__ import annotations

from typing import Any

import torch


def proportional_controller(obs: dict[str, Any]) -> dict[str, float]:
    """Simple proportional controller: move eef toward object, grip when close.

    Args:
        obs: Standardized observation dict with keys like:
            - eef_pos:     end-effector position (x, y, z)
            - object_pos:  target object position (x, y, z)
            - gripper_pos: gripper joint position

    Returns:
        Action dict with keys mapped to action indices:
            - x, y, z:     target position commands
            - gripper:     <0 = close, >=0 = open (BinaryJointAction convention)
    """
    eef_pos = obs.get("eef_pos")
    object_pos = obs.get("object_pos")

    if eef_pos is None or object_pos is None:
        # No position info — hover and keep gripper open
        return {"x": 0.35, "y": 0.0, "z": 0.25, "gripper": 1.0}

    # Flatten batched observations if needed (IsaacLab uses shape (N, ...))
    if hasattr(eef_pos, "dim") and eef_pos.dim() > 1:
        eef = eef_pos[0]
    else:
        eef = eef_pos

    if hasattr(object_pos, "dim") and object_pos.dim() > 1:
        obj = object_pos[0]
    else:
        obj = object_pos

    # Compute deltas
    dx = float(obj[0] - eef[0])
    dy = float(obj[1] - eef[1])
    dz = float(obj[2] - eef[2])
    dist = (dx**2 + dy**2 + dz**2) ** 0.5

    # Proportional gain
    kp = 5.0

    action = {
        "x": eef[0] + dx * kp,
        "y": eef[1] + dy * kp,
        "z": max(eef[2] + dz * kp, 0.08),  # don't go below table
    }

    # Close gripper when close (BinaryJointAction: negative = close)
    action["gripper"] = -1.0 if dist < 0.05 else 1.0

    return action


def random_exploration(obs: dict[str, Any]) -> torch.Tensor:
    """Random policy returning a raw torch tensor (also valid).

    run_eval.py will pass this through _normalize_action() which accepts
    torch.Tensor, numpy.ndarray, and dict.
    """
    return torch.randn(1, 8) * 0.2
