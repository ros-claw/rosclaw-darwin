"""Residual action schemas and policy implementations."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ResidualAction(BaseModel):
    delta_pos: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    delta_rot: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    delta_gripper: float = 0.0
    lift_speed_scale: float = 1.0
    active_axes: list[bool] = Field(default_factory=lambda: [False] * 7)
    confidence: float = 0.0
    reason: str | None = None


class ResidualPolicy(ABC):
    """Abstract base class for residual correction policies."""

    @abstractmethod
    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        """Predict a residual action given observation and sensor signals."""


DEFAULT_RESIDUAL_LIMITS: dict[str, float] = {
    "positional": 0.005,
    "rotational": 0.03,
    "gripper": 0.05,
}


class ResidualPolicyWrapper:
    """Wraps a base heuristic action with a residual policy."""

    residual_limits: dict[str, float] = {
        "positional": 0.005,
        "rotational": 0.03,
        "gripper": 0.05,
    }

    def __init__(self, residual_policy: ResidualPolicy) -> None:
        self.residual_policy = residual_policy

    def compute_final_action(
        self,
        heuristic_action: list[float],
        obs: dict,
        residual_action: ResidualAction | None = None,
        **signals: Any,
    ) -> list[float]:
        """Return heuristic_action + clipped residual.

        If ``residual_action`` is provided it is reused; otherwise the wrapped
        policy is queried.  This lets callers avoid a double ``predict()`` call
        when they already have the residual action.
        """
        if residual_action is None:
            contact_signal = signals.get("contact_signal")
            slip_signal = signals.get("slip_signal")
            grip_quality_signal = signals.get("grip_quality_signal")
            phase = signals.get("phase", "UNKNOWN")
            residual_action = self.residual_policy.predict(
                obs,
                contact_signal,
                slip_signal,
                grip_quality_signal,
                phase,
            )

        residual_vector = (
            residual_action.delta_pos
            + residual_action.delta_rot
            + [residual_action.delta_gripper]
        )

        active_axes = residual_action.active_axes
        if len(active_axes) < 7:
            active_axes = active_axes + [False] * (7 - len(active_axes))

        clipped_residual: list[float] = []
        for i, (val, active) in enumerate(zip(residual_vector, active_axes)):
            if not active:
                clipped_residual.append(0.0)
                continue
            if i < 3:
                limit = self.residual_limits["positional"]
            elif i < 6:
                limit = self.residual_limits["rotational"]
            else:
                limit = self.residual_limits["gripper"]
            clipped_residual.append(max(-limit, min(limit, val)))

        # Ensure a flat list of floats.  Some callers pass a batch-shaped tensor
        # whose ``tolist()`` yields ``[[...]]``; unwrap one level if needed.
        heuristic_action = list(heuristic_action)
        if heuristic_action and isinstance(heuristic_action[0], list):
            heuristic_action = heuristic_action[0]
        heuristic_action = [float(v) for v in heuristic_action]

        if len(heuristic_action) < 7:
            heuristic_action = heuristic_action + [0.0] * (7 - len(heuristic_action))

        # Apply lift speed scale to the z-axis during lift/hold phases.
        phase = signals.get("phase", "UNKNOWN")
        if phase in ("LIFT", "LIFT_VERIFY", "HOLD", "RECOVERY") and residual_action.lift_speed_scale != 1.0:
            heuristic_action[2] *= float(residual_action.lift_speed_scale)

        # Only correct the first 7 DOFs; preserve any extra action dimensions.
        n = min(len(heuristic_action), len(clipped_residual))
        final = [heuristic_action[i] + clipped_residual[i] for i in range(n)]
        final.extend(heuristic_action[n:])
        if len(final) < 7:
            final = final + [0.0] * (7 - len(final))
        return final

    def residual_action_norm(self, residual_action: ResidualAction) -> float:
        residual_vector = (
            residual_action.delta_pos
            + residual_action.delta_rot
            + [residual_action.delta_gripper]
        )
        return math.sqrt(sum(v * v for v in residual_vector))


class ResidualNonePolicy(ResidualPolicy):
    """No-op residual policy that always returns zero residual."""

    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        return ResidualAction(
            delta_pos=[0.0, 0.0, 0.0],
            delta_rot=[0.0, 0.0, 0.0],
            delta_gripper=0.0,
            active_axes=[False] * 7,
            confidence=0.0,
            reason=None,
        )


class ResidualSeed24GuardPolicy(ResidualPolicy):
    """Guard policy for seed-24 low-Z / open-gripper conditions."""

    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        if phase not in ("GRASP", "CONTACT_VERIFY", "PRE_LIFT"):
            return ResidualNonePolicy().predict(
                observation, contact_signal, slip_signal, grip_quality_signal, phase
            )

        if grip_quality_signal is None:
            return ResidualNonePolicy().predict(
                observation, contact_signal, slip_signal, grip_quality_signal, phase
            )

        low_z = grip_quality_signal.get("low_object_z", False)
        too_open = grip_quality_signal.get("gripper_too_open", False)

        if low_z and too_open:
            active_axes = [False] * 7
            active_axes[2] = True
            active_axes[6] = True
            return ResidualAction(
                delta_pos=[0.0, 0.0, -0.003],
                delta_rot=[0.0, 0.0, 0.0],
                delta_gripper=-0.03,
                active_axes=active_axes,
                confidence=0.7,
                reason="seed24_guard_low_z_open_gripper",
            )

        return ResidualNonePolicy().predict(
            observation, contact_signal, slip_signal, grip_quality_signal, phase
        )


class ResidualSlipGuardPolicy(ResidualPolicy):
    """Guard policy that reduces rotational / yaw motion when slip risk is high."""

    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        if slip_signal is None:
            return ResidualNonePolicy().predict(
                observation, contact_signal, slip_signal, grip_quality_signal, phase
            )

        slip_risk = slip_signal.get("slip_risk")
        slip_score = slip_signal.get("slip_score")

        high_risk = slip_risk == "high"
        numeric_high = isinstance(slip_score, (int, float)) and slip_score > 2.0

        if high_risk or numeric_high:
            active_axes = [False] * 7
            active_axes[3] = True
            active_axes[4] = True
            active_axes[5] = True
            active_axes[6] = True
            return ResidualAction(
                delta_pos=[0.0, 0.0, 0.0],
                delta_rot=[-0.02, 0.0, -0.02],
                delta_gripper=0.02,
                active_axes=active_axes,
                confidence=0.6,
                reason="slip_guard_reduce_rot_yaw",
            )

        return ResidualNonePolicy().predict(
            observation, contact_signal, slip_signal, grip_quality_signal, phase
        )


__all__ = [
    "ResidualAction",
    "ResidualPolicy",
    "DEFAULT_RESIDUAL_LIMITS",
    "ResidualPolicyWrapper",
    "ResidualNonePolicy",
    "ResidualSeed24GuardPolicy",
    "ResidualSlipGuardPolicy",
]
