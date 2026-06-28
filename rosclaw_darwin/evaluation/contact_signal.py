"""ContactSignal abstraction for contact-aware residual evolution.

This module provides a unified, source-agnostic representation of contact
state.  It is intentionally sensor-agnostic: the primary implementation
computes a kinematic contact proxy from gripper width and object motion, the
same signals already available in the goal-pose trace.  Future sources
(gripper joint torque, Isaac contact force, tactile/FT sensors) can plug in
without changing consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContactSignal:
    """Unified per-step contact signal.

    Fields are intentionally conservative.  When a real sensor is not
    available the corresponding estimate is ``None``; consumers must fall
    back to kinematic proxies.
    """

    step: int
    phase: str
    source: str

    # Kinematic / gripper observations
    gripper_width: float | None = None
    gripper_command: float | None = None
    gripper_width_error: float | None = None
    object_z: float | None = None
    eef_z: float | None = None
    object_eef_distance: float | None = None
    object_displacement_from_grasp: float | None = None

    # Force / contact proxies (populated when a source can estimate them)
    normal_force_estimate: float | None = None
    tangential_force_proxy: float | None = None
    torsional_friction_proxy: float | None = None

    # Merged output
    contact_confidence: float = 0.0
    contact_state: str = "unknown"
    reason: str | None = None


@dataclass
class ContactSignalProvider:
    """Compute ``ContactSignal`` from one or more sources.

    The kinematic source mirrors the logic previously inlined in
    ``heuristic_policy._classify_contact_proxy``.  It classifies contact into:

    - ``no_contact`` — gripper still wide open after a close attempt.
    - ``pushed_away`` — object moved away from the gripper during close.
    - ``likely_contact`` — gripper blocked at a wide aperture and object stayed.
    - ``weak_contact_no_lift`` — gripper closed tightly but object did not move.
    - ``unknown`` — insufficient information.

    The gripper-joint source estimates contact from the gap between commanded
    and actual gripper width.
    """

    gripper_close_threshold: float = 0.012
    grasp_dist_threshold: float = 0.04
    no_contact_width: float = 0.08
    push_away_delta: float = 0.02
    push_away_distance_margin: float = 0.02
    weak_contact_open_factor: float = 1.5

    # State accumulated across the episode for the kinematic source.
    _grasp_start_object_pos: Any = field(default=None, repr=False)
    _grasp_start_eef_pos: Any = field(default=None, repr=False)

    def reset(self) -> None:
        """Clear accumulated grasp-start reference state."""
        self._grasp_start_object_pos = None
        self._grasp_start_eef_pos = None

    @staticmethod
    def _norm(a: Any, b: Any) -> float | None:
        """Return Euclidean distance between two 3-D points if both are present."""
        if a is None or b is None:
            return None
        try:
            import torch

            if isinstance(a, torch.Tensor):
                a = a.detach().cpu()
            if isinstance(b, torch.Tensor):
                b = b.detach().cpu()
        except Exception:
            pass
        try:
            import numpy as np

            a = np.asarray(a, dtype=float)
            b = np.asarray(b, dtype=float)
            return float(np.linalg.norm(a - b))
        except Exception:
            return None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            import torch

            if isinstance(value, torch.Tensor):
                value = value.item()
        except Exception:
            pass
        try:
            return float(value)
        except Exception:
            return None

    def compute_from_kinematics(
        self,
        frame: dict[str, Any],
        grasp_start: dict[str, Any] | None = None,
    ) -> ContactSignal:
        """Classify contact from gripper width and object/eef motion.

        ``frame`` must contain at least ``gripper_pos`` and optionally
        ``object_pos`` / ``eef_pos``.  If ``grasp_start`` is provided it is
        used as the reference; otherwise the provider remembers the first frame
        with object/eef positions.
        """
        step = int(frame.get("step", 0))
        phase = str(frame.get("phase", "UNKNOWN"))

        gripper_width = self._as_float(frame.get("gripper_pos"))
        object_pos = frame.get("object_pos")
        eef_pos = frame.get("eef_pos")

        if grasp_start is not None:
            self._grasp_start_object_pos = grasp_start.get("object_pos") or self._grasp_start_object_pos
            self._grasp_start_eef_pos = grasp_start.get("eef_pos") or self._grasp_start_eef_pos

        if self._grasp_start_object_pos is None and object_pos is not None:
            self._grasp_start_object_pos = object_pos
        if self._grasp_start_eef_pos is None and eef_pos is not None:
            self._grasp_start_eef_pos = eef_pos

        object_eef_distance = self._norm(object_pos, eef_pos)
        object_displacement = self._norm(object_pos, self._grasp_start_object_pos)
        start_distance = self._norm(self._grasp_start_object_pos, self._grasp_start_eef_pos)

        object_z = self._as_float(frame.get("object_z")) or self._as_float(
            object_pos[2] if object_pos is not None and len(object_pos) > 2 else None
        )
        eef_z = self._as_float(frame.get("eef_z")) or self._as_float(
            eef_pos[2] if eef_pos is not None and len(eef_pos) > 2 else None
        )

        contact_state = "unknown"
        confidence = 0.0
        reason: str | None = None

        if gripper_width is None or object_pos is None or eef_pos is None:
            contact_state = "unknown"
            confidence = 0.0
            reason = "missing_observation"
        elif gripper_width > self.no_contact_width:
            contact_state = "no_contact"
            confidence = 0.8
            reason = f"gripper_still_open={gripper_width:.4f}"
        elif object_displacement is not None and (
            object_displacement > self.push_away_delta
            or (object_eef_distance is not None and start_distance is not None and object_eef_distance > start_distance + self.push_away_distance_margin)
        ):
            contact_state = "pushed_away"
            confidence = 0.8
            reason = f"object_delta={object_displacement:.4f}"
        elif gripper_width > self.gripper_close_threshold * self.weak_contact_open_factor:
            contact_state = "likely_contact"
            confidence = 0.7
            reason = f"gripper_blocked={gripper_width:.4f}"
        else:
            contact_state = "weak_contact_no_lift"
            confidence = 0.6
            reason = f"gripper_closed={gripper_width:.4f}"

        # Simple normal-force proxy: the more the gripper is blocked above the
        # empty-close threshold, the larger the proxy.  This is not Newtons; it
        # is a normalized index for residual learning.
        normal_force_estimate: float | None = None
        if gripper_width is not None and gripper_width <= self.no_contact_width:
            normal_force_estimate = max(0.0, self.no_contact_width - gripper_width) / max(1e-6, self.no_contact_width)

        return ContactSignal(
            step=step,
            phase=phase,
            source="kinematics",
            gripper_width=gripper_width,
            object_z=object_z,
            eef_z=eef_z,
            object_eef_distance=object_eef_distance,
            object_displacement_from_grasp=object_displacement,
            normal_force_estimate=round(normal_force_estimate, 4) if normal_force_estimate is not None else None,
            contact_confidence=round(confidence, 4),
            contact_state=contact_state,
            reason=reason,
        )

    def compute_from_gripper_joint(self, frame: dict[str, Any]) -> ContactSignal:
        """Estimate contact from the commanded vs actual gripper width gap."""
        step = int(frame.get("step", 0))
        phase = str(frame.get("phase", "UNKNOWN"))

        gripper_width = self._as_float(frame.get("gripper_pos"))
        gripper_command = self._as_float(frame.get("gripper_cmd"))
        width_error = (
            abs(gripper_width - gripper_command)
            if gripper_width is not None and gripper_command is not None
            else None
        )

        contact_state = "unknown"
        confidence = 0.0
        reason: str | None = None

        if width_error is None:
            contact_state = "unknown"
            confidence = 0.0
            reason = "missing_command"
        elif gripper_command < 0.5 and width_error > 0.01:
            # Commanded close but fingers could not reach command => blocked.
            contact_state = "likely_contact"
            confidence = 0.75
            reason = f"close_command_unmet_error={width_error:.4f}"
        elif gripper_command < 0.5 and width_error <= 0.01:
            contact_state = "weak_contact_no_lift"
            confidence = 0.5
            reason = f"close_command_met_error={width_error:.4f}"
        else:
            contact_state = "no_contact"
            confidence = 0.4
            reason = f"open_command_error={width_error:.4f}"

        return ContactSignal(
            step=step,
            phase=phase,
            source="gripper_joint",
            gripper_width=gripper_width,
            gripper_command=gripper_command,
            gripper_width_error=round(width_error, 4) if width_error is not None else None,
            contact_confidence=round(confidence, 4),
            contact_state=contact_state,
            reason=reason,
        )

    @staticmethod
    def merge_sources(signals: list[ContactSignal]) -> ContactSignal | None:
        """Merge multiple contact signals into a single consensus signal.

        Current strategy: prefer the signal with highest confidence; if two
        sources disagree with similar confidence, downgrade to ``unknown`` and
        record the conflict.
        """
        if not signals:
            return None

        # Sort by confidence descending.
        ranked = sorted(signals, key=lambda s: s.contact_confidence, reverse=True)
        best = ranked[0]
        if len(ranked) == 1:
            return best

        second = ranked[1]
        # If the top two sources disagree and the gap is small, mark conflict.
        if best.contact_state != second.contact_state and best.contact_confidence - second.contact_confidence < 0.2:
            return ContactSignal(
                step=best.step,
                phase=best.phase,
                source="merged_conflict",
                gripper_width=best.gripper_width,
                gripper_command=best.gripper_command,
                gripper_width_error=best.gripper_width_error,
                object_z=best.object_z,
                eef_z=best.eef_z,
                object_eef_distance=best.object_eef_distance,
                object_displacement_from_grasp=best.object_displacement_from_grasp,
                contact_confidence=round((best.contact_confidence + second.contact_confidence) / 2, 4),
                contact_state="unknown",
                reason=f"conflict:{best.source}:{best.contact_state}_vs_{second.source}:{second.contact_state}",
            )

        return best

    def process_trace(
        self,
        trace: list[dict[str, Any]],
        include_gripper_joint: bool = False,
    ) -> list[ContactSignal]:
        """Convenience method: run kinematics (+ optionally gripper_joint) on a trace."""
        merged: list[ContactSignal] = []
        for frame in trace:
            sources = [self.compute_from_kinematics(frame)]
            if include_gripper_joint:
                sources.append(self.compute_from_gripper_joint(frame))
            consensus = self.merge_sources(sources)
            merged.append(consensus if consensus is not None else sources[0])
        return merged
