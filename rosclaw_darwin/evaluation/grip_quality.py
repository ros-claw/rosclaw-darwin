"""Closed-loop grip-quality monitor for early grasp-failure detection.

The monitor consumes per-step goal_pose traces and emits a ``GripQualitySignal``
each step.  It looks for the deterministic seed-24 signature:

- the object is low at the moment the gripper starts to close
  (``object_z_at_grasp`` is below normal),
- the gripper does not close tightly (``gripper_width_after_close`` stays high),
- the object does not follow the gripper during the guarded lift
  (``object_height_response_to_lift`` is small).

Only when all three indicators line up do we flag
``trigger_micro_recovery=True``.  The trigger is restricted to the
``GRASP`` / ``CONTACT_VERIFY`` / ``LIFT_VERIFY`` phases so that normal seeds in
``LIFT`` / ``REORIENT`` are never side-effected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rosclaw_darwin.evaluation.yaw_coupling import _get


@dataclass(frozen=True)
class GripQualitySignal:
    """Per-step grip-quality state emitted by ``GripQualityMonitor``."""

    step: int
    phase: str
    object_z_at_grasp: float | None
    gripper_width_after_close: float | None
    object_height_response_to_lift: float | None
    object_follows_eef_score: float | None
    grip_quality_score: float
    grip_failure_risk: float
    trigger_micro_recovery: bool
    reason: str | None

    @property
    def low_object_z(self) -> bool:
        return self.object_z_at_grasp is not None and self.object_z_at_grasp < 0.023

    @property
    def gripper_too_open(self) -> bool:
        return self.gripper_width_after_close is not None and self.gripper_width_after_close > 0.035

    @property
    def weak_lift_response(self) -> bool:
        return (
            self.object_height_response_to_lift is not None
            and self.object_height_response_to_lift < 0.005
        )


@dataclass
class GripQualityMonitorConfig:
    """Tuning knobs for the grip-quality monitor.

    Thresholds are tuned against the official ``dex_cube`` 0:99 distribution.
    A value that is too aggressive will false-trigger on normal seeds; a value
    that is too conservative will miss seed-24-like signatures.
    """

    # Phase whitelist for recovery triggers.  We deliberately do NOT include
    # REORIENT / ALIGN because those are handled by the slip monitor.  LIFT is
    # included so that a seed-24-like weak lift response can still trigger the
    # guarded micro-recovery if the early GRASP risk threshold is not crossed.
    recovery_trigger_phases: set[str] = field(
        default_factory=lambda: {"GRASP", "CONTACT_VERIFY", "LIFT_VERIFY", "LIFT"}
    )

    # Signature thresholds (SI units / gripper command units).
    object_z_low_threshold: float = 0.023  # m
    gripper_width_high_threshold: float = 0.035  # gripper command units
    gripper_close_attempted_threshold: float = 0.05  # must have tried to close
    lift_response_z_threshold: float = 0.005  # m

    # Minimum gripper width observed during GRASP is considered the "after
    # close" width.  We wait until the gripper has had time to move.
    min_grasp_steps_for_width: int = 10

    # We only declare weak lift response after the guarded lift has run for
    # at least this many steps.
    min_lift_verify_steps_for_response: int = 3

    # Once triggered, do not re-trigger for the rest of the episode.
    lock_after_trigger: bool = True


class GripQualityMonitor:
    """Compute per-step grip-quality signals from a goal_pose trace."""

    def __init__(self, config: GripQualityMonitorConfig | None = None) -> None:
        self.config = config or GripQualityMonitorConfig()
        self._object_z_at_grasp: float | None = None
        self._min_gripper_width_seen: float | None = None
        self._grasp_steps_seen: int = 0
        self._lift_verify_start_object_z: float | None = None
        self._lift_verify_steps: int = 0
        self._triggered: bool = False

    def reset(self) -> None:
        """Clear all state; call at the start of each episode."""
        self._object_z_at_grasp = None
        self._min_gripper_width_seen = None
        self._grasp_steps_seen = 0
        self._lift_verify_start_object_z = None
        self._lift_verify_steps = 0
        self._triggered = False

    def update(self, record: dict[str, Any]) -> GripQualitySignal:
        """Process a single new record and return its ``GripQualitySignal``."""
        cfg = self.config
        step = int(record.get("step", 0))
        phase = str(record.get("phase", "UNKNOWN"))

        object_z = _get(record, "object_z")
        gripper_pos = _get(record, "gripper_pos")
        eef_z = _get(record, "eef_z")

        # Capture object z when the gripper first starts closing.  We use the
        # first GRASP step with a valid object_z as the canonical height.
        if phase == "GRASP" and object_z is not None:
            if self._object_z_at_grasp is None:
                self._object_z_at_grasp = object_z
            self._grasp_steps_seen += 1
            if gripper_pos is not None and self._grasp_steps_seen >= cfg.min_grasp_steps_for_width:
                if (
                    self._min_gripper_width_seen is None
                    or gripper_pos < self._min_gripper_width_seen
                ):
                    self._min_gripper_width_seen = gripper_pos

        # Capture the guarded-lift baseline.  The policy uses "LIFT" for the
        # actual lift motion and "LIFT_VERIFY" only when a separate verification
        # state exists, so accept both.
        if phase in ("LIFT_VERIFY", "LIFT"):
            if self._lift_verify_start_object_z is None and object_z is not None:
                self._lift_verify_start_object_z = object_z
            self._lift_verify_steps += 1

        # Current lift response relative to the start of the guarded lift.  If we
        # have not reached LIFT/LIFT_VERIFY yet, compare against the grasp height.
        baseline_z = self._lift_verify_start_object_z
        if baseline_z is None:
            baseline_z = self._object_z_at_grasp
        object_height_response_to_lift = (
            object_z - baseline_z if object_z is not None and baseline_z is not None else None
        )

        # Simple object-follows-eef score: vertical gap between gripper and
        # object.  Smaller is better.  None if data missing.
        object_follows_eef_score: float | None = None
        if object_z is not None and eef_z is not None:
            object_follows_eef_score = abs(eef_z - object_z)

        # Build binary indicators.
        low_z = (
            self._object_z_at_grasp is not None
            and self._object_z_at_grasp < cfg.object_z_low_threshold
        )
        gripper_attempted = (
            self._min_gripper_width_seen is not None
            and self._min_gripper_width_seen < cfg.gripper_close_attempted_threshold
        )
        gripper_too_open = (
            gripper_attempted
            and self._min_gripper_width_seen is not None
            and self._min_gripper_width_seen > cfg.gripper_width_high_threshold
        )
        weak_lift = (
            phase in ("LIFT_VERIFY", "LIFT")
            and self._lift_verify_steps >= cfg.min_lift_verify_steps_for_response
            and object_height_response_to_lift is not None
            and object_height_response_to_lift < cfg.lift_response_z_threshold
        )

        # Risk is the fraction of the three signature indicators that are true.
        indicators = [low_z, gripper_too_open, weak_lift]
        active = [i for i in indicators if i]
        grip_failure_risk = len(active) / len(indicators) if indicators else 0.0
        grip_quality_score = 1.0 - grip_failure_risk

        # Build a human-readable reason string.
        reasons: list[str] = []
        if low_z:
            reasons.append(f"low_object_z={self._object_z_at_grasp:.4f}")
        if gripper_too_open:
            reasons.append(f"gripper_too_open={self._min_gripper_width_seen:.4f}")
        if weak_lift:
            reasons.append(f"weak_lift_response={object_height_response_to_lift:.4f}")
        reason = "; ".join(reasons) if reasons else None

        # Trigger only when all three indicators are active and we are in an
        # allowed phase.  The three-way AND is what keeps the false-positive
        # rate low on normal seeds.
        can_trigger = (
            not (cfg.lock_after_trigger and self._triggered)
            and phase in cfg.recovery_trigger_phases
            and low_z
            and gripper_too_open
            and weak_lift
        )
        if can_trigger:
            self._triggered = True

        return GripQualitySignal(
            step=step,
            phase=phase,
            object_z_at_grasp=self._object_z_at_grasp,
            gripper_width_after_close=self._min_gripper_width_seen,
            object_height_response_to_lift=object_height_response_to_lift,
            object_follows_eef_score=object_follows_eef_score,
            grip_quality_score=round(grip_quality_score, 4),
            grip_failure_risk=round(grip_failure_risk, 4),
            trigger_micro_recovery=can_trigger,
            reason=reason,
        )

    def process_trace(self, trace: list[dict[str, Any]]) -> list[GripQualitySignal]:
        """Return a ``GripQualitySignal`` for every step in ``trace``."""
        self.reset()
        return [self.update(record) for record in trace]
