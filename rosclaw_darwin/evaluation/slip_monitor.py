"""Closed-loop slip detection from kinematic proxies.

The monitor consumes per-step goal_pose traces and emits a ``SlipSignal`` each
step.  It separates four physical mechanisms:

- torsional_slip  : object yaw diverges from gripper yaw while lifted
- vertical_slip   : object height drops while the gripper is stable
- pose_drift      : object position drifts away from the gripper
- drop            : object falls below the lifted threshold

The overall ``slip_score`` is a weighted sum of normalized component scores.
A component is flagged when it exceeds its own threshold; an *event* is declared
when the score crosses the configured event threshold.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from rosclaw_darwin.evaluation.yaw_coupling import _angle_diff, _get


@dataclass(frozen=True)
class SlipSignal:
    """Per-step slip state emitted by ``SlipMonitor``."""

    step: int
    phase: str
    slip_score: float
    torsional_slip: bool
    vertical_slip: bool
    pose_drift: bool
    drop: bool
    no_slip: bool

    @property
    def any_slip(self) -> bool:
        return self.torsional_slip or self.vertical_slip or self.pose_drift or self.drop


@dataclass
class SlipMonitorConfig:
    """Tuning knobs for the kinematic slip monitor.

    All thresholds are in SI units (metres / radians).  The weights are used to
    combine *normalized* component scores into the aggregate ``slip_score``.
    """

    # Component thresholds
    torsional_slip_threshold: float = 0.3  # rad
    yaw_error_increase_threshold: float = 0.2  # rad
    position_drift_threshold: float = 0.02  # m
    vertical_drop_threshold: float = 0.005  # m
    eef_stability_threshold: float = 0.001  # m
    drop_height_threshold: float = 0.08  # m (object_z below this is "dropped")
    min_lift_height: float = 0.1  # m

    # Window over which to look back for drift / drop baselines.
    window_size: int = 10

    # Minimum contiguous steps above threshold to declare a slip event.
    min_event_steps: int = 5

    # Score threshold above which a contiguous event is declared.
    event_score_threshold: float = 3.5

    # Weights for the aggregate slip score.  Components are divided by their
    # thresholds before weighting, so a weighted sum > 1.0 means at least one
    # component is above threshold.
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "torsional": 0.40,
            "yaw_error": 0.30,
            "pose_drift": 0.20,
            "vertical": 0.10,
        }
    )


class SlipMonitor:
    """Compute per-step slip signals from a goal_pose trace."""

    def __init__(self, config: SlipMonitorConfig | None = None) -> None:
        self.config = config or SlipMonitorConfig()
        self._initial_object_z: float | None = None
        self._recent_object_yaw_error: deque[float] = deque(maxlen=self.config.window_size)
        self._recent_object_eef_dist: deque[float] = deque(maxlen=self.config.window_size)
        self._recent_object_z: deque[float] = deque(maxlen=self.config.window_size)
        self._recent_eef_pos: deque[tuple[float, float, float]] = deque(maxlen=self.config.window_size)

    def reset(self) -> None:
        """Clear all rolling buffers and the initial-object-z baseline."""
        self._initial_object_z = None
        self._recent_object_yaw_error.clear()
        self._recent_object_eef_dist.clear()
        self._recent_object_z.clear()
        self._recent_eef_pos.clear()

    def update(self, record: dict[str, Any]) -> SlipSignal:
        """Process a single new record and return its ``SlipSignal``."""
        cfg = self.config

        obj_yaw = _get(record, "object_yaw")
        eef_yaw = _get(record, "eef_yaw")
        target_yaw = _get(record, "target_yaw")
        obj_z = _get(record, "object_z")
        obj_x = _get(record, "object_x")
        obj_y = _get(record, "object_y")
        eef_x = _get(record, "eef_x")
        eef_y = _get(record, "eef_y")
        eef_z = _get(record, "eef_z")

        if self._initial_object_z is None and obj_z is not None:
            self._initial_object_z = obj_z

        lifted = (
            obj_z is not None
            and self._initial_object_z is not None
            and obj_z > self._initial_object_z + cfg.min_lift_height
        )

        torsional_score = 0.0
        if obj_yaw is not None and eef_yaw is not None:
            torsional_score = abs(_angle_diff(obj_yaw, eef_yaw))

        yaw_error_inc_score = 0.0
        if target_yaw is not None and obj_yaw is not None:
            yaw_err = abs(_angle_diff(target_yaw, obj_yaw))
            if self._recent_object_yaw_error:
                yaw_error_inc_score = max(
                    0.0, yaw_err - min(self._recent_object_yaw_error)
                )
            self._recent_object_yaw_error.append(yaw_err)

        pose_drift_score = 0.0
        if (
            obj_x is not None
            and obj_y is not None
            and obj_z is not None
            and eef_x is not None
            and eef_y is not None
            and eef_z is not None
        ):
            dist = math.sqrt(
                (obj_x - eef_x) ** 2
                + (obj_y - eef_y) ** 2
                + (obj_z - eef_z) ** 2
            )
            if self._recent_object_eef_dist:
                pose_drift_score = max(0.0, dist - min(self._recent_object_eef_dist))
            self._recent_object_eef_dist.append(dist)

        vertical_score = 0.0
        drop = False
        if obj_z is not None:
            if self._recent_object_z:
                vertical_score = max(0.0, max(self._recent_object_z) - obj_z)
            self._recent_object_z.append(obj_z)
            if lifted and obj_z < cfg.drop_height_threshold:
                drop = True

        eef_stable = False
        if eef_x is not None and eef_y is not None and eef_z is not None:
            self._recent_eef_pos.append((eef_x, eef_y, eef_z))
            if len(self._recent_eef_pos) >= 2:
                first_pos = self._recent_eef_pos[0]
                max_disp = max(
                    abs(p[i] - first_pos[i])
                    for p in self._recent_eef_pos
                    for i in range(3)
                )
                eef_stable = max_disp < cfg.eef_stability_threshold

        if vertical_score > 0 and not eef_stable:
            vertical_score = 0.0

        w = cfg.weights
        score = 0.0
        torsional_flag = lifted and torsional_score > cfg.torsional_slip_threshold
        yaw_error_flag = lifted and yaw_error_inc_score > cfg.yaw_error_increase_threshold
        pose_drift_flag = lifted and pose_drift_score > cfg.position_drift_threshold
        vertical_flag = lifted and vertical_score > cfg.vertical_drop_threshold

        if torsional_flag:
            score += w.get("torsional", 0.0) * (torsional_score / cfg.torsional_slip_threshold)
        if yaw_error_flag:
            score += w.get("yaw_error", 0.0) * (yaw_error_inc_score / cfg.yaw_error_increase_threshold)
        if pose_drift_flag:
            score += w.get("pose_drift", 0.0) * (pose_drift_score / cfg.position_drift_threshold)
        if vertical_flag:
            score += w.get("vertical", 0.0) * (vertical_score / cfg.vertical_drop_threshold)
        if drop:
            score += 1.0

        any_flag = torsional_flag or yaw_error_flag or pose_drift_flag or vertical_flag or drop

        return SlipSignal(
            step=int(record.get("step", 0)),
            phase=str(record.get("phase", "UNKNOWN")),
            slip_score=float(score),
            torsional_slip=torsional_flag,
            vertical_slip=vertical_flag,
            pose_drift=pose_drift_flag,
            drop=drop,
            no_slip=not any_flag,
        )

    def process_trace(self, trace: list[dict[str, Any]]) -> list[SlipSignal]:
        """Return a ``SlipSignal`` for every step in ``trace``."""
        self.reset()
        return [self.update(record) for record in trace]

    def detect_events(
        self,
        trace: list[dict[str, Any]],
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return contiguous slip events where the score exceeds ``threshold``.

        Each event contains: ``start_step``, ``end_step``, ``max_score``,
        ``dominant_type``, ``steps`` (count), ``first_phase``.
        """
        cfg = self.config
        threshold = cfg.event_score_threshold if threshold is None else threshold
        signals = self.process_trace(trace)

        events: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for sig in signals:
            in_event = sig.slip_score > threshold
            if in_event:
                if current is None:
                    current = {
                        "start_step": sig.step,
                        "end_step": sig.step,
                        "max_score": sig.slip_score,
                        "dominant_type": self._dominant_type(sig),
                        "first_phase": sig.phase,
                        "steps": 1,
                    }
                else:
                    current["end_step"] = sig.step
                    current["max_score"] = max(current["max_score"], sig.slip_score)
                    current["steps"] += 1
            else:
                if current is not None:
                    if current["steps"] >= cfg.min_event_steps:
                        events.append(current)
                    current = None

        if current is not None and current["steps"] >= cfg.min_event_steps:
            events.append(current)

        return events

    @staticmethod
    def _dominant_type(sig: SlipSignal) -> str:
        if sig.drop:
            return "drop"
        if sig.torsional_slip:
            return "torsional_slip"
        if sig.pose_drift:
            return "pose_drift"
        if sig.vertical_slip:
            return "vertical_slip"
        return "unknown"
