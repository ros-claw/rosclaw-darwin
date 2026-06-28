"""Unit tests for the closed-loop slip monitor."""

from __future__ import annotations

import math

from rosclaw_darwin.evaluation.slip_monitor import (
    SlipMonitor,
    SlipMonitorConfig,
    SlipSignal,
)


def _record(
    step: int,
    phase: str,
    *,
    object_yaw: float = 0.0,
    eef_yaw: float = 0.0,
    target_yaw: float = 0.0,
    object_z: float = 0.2,
    object_x: float = 0.0,
    object_y: float = 0.0,
    eef_x: float = 0.0,
    eef_y: float = 0.0,
    eef_z: float = 0.2,
) -> dict[str, float | str | int]:
    """Build a single trace record."""
    return {
        "step": step,
        "phase": phase,
        "object_yaw": object_yaw,
        "eef_yaw": eef_yaw,
        "target_yaw": target_yaw,
        "object_z": object_z,
        "object_x": object_x,
        "object_y": object_y,
        "eef_x": eef_x,
        "eef_y": eef_y,
        "eef_z": eef_z,
    }


def _make_lifted_trace(
    *,
    lift_start: int = 5,
    lift_steps: int = 20,
    object_yaw: float = 0.0,
    eef_yaw: float = 0.0,
    target_yaw: float = 0.0,
    object_z_final: float = 0.35,
) -> list[dict[str, float | str | int]]:
    """Return a stable lifted trace with no slip."""
    trace: list[dict[str, float | str | int]] = []
    for i in range(lift_start):
        trace.append(_record(i, "APPROACH", object_z=0.2))
    for i in range(lift_steps):
        t = i / max(lift_steps - 1, 1)
        z = 0.2 + t * (object_z_final - 0.2)
        trace.append(
            _record(
                lift_start + i,
                "LIFT",
                object_yaw=object_yaw,
                eef_yaw=eef_yaw,
                target_yaw=target_yaw,
                object_z=z,
                eef_z=z,
            )
        )
    return trace


class TestSlipSignal:
    def test_any_slip_property(self):
        sig = SlipSignal(
            step=0,
            phase="LIFT",
            slip_score=1.0,
            torsional_slip=False,
            vertical_slip=False,
            pose_drift=False,
            drop=False,
            no_slip=True,
        )
        assert not sig.any_slip

        sig2 = SlipSignal(
            step=0,
            phase="LIFT",
            slip_score=1.0,
            torsional_slip=True,
            vertical_slip=False,
            pose_drift=False,
            drop=False,
            no_slip=False,
        )
        assert sig2.any_slip


class TestSlipMonitor:
    def test_empty_trace(self):
        monitor = SlipMonitor()
        assert monitor.process_trace([]) == []
        assert monitor.detect_events([]) == []

    def test_no_slip_success_trace(self):
        trace = _make_lifted_trace()
        monitor = SlipMonitor()
        signals = monitor.process_trace(trace)
        assert len(signals) == len(trace)
        assert all(s.no_slip for s in signals)
        assert monitor.detect_events(trace) == []

    def test_torsional_slip_detected_after_lift(self):
        cfg = SlipMonitorConfig(event_score_threshold=1.0, min_event_steps=3)
        monitor = SlipMonitor(cfg)
        # Stable lift, then the object yaws away from the gripper.
        trace = _make_lifted_trace(
            lift_steps=10, object_yaw=0.8, eef_yaw=0.0, target_yaw=0.8
        )
        events = monitor.detect_events(trace)
        assert len(events) >= 1
        assert events[0]["dominant_type"] == "torsional_slip"
        # Event should start during or after LIFT, never during APPROACH.
        assert events[0]["start_step"] >= 5

    def test_pre_lift_divergence_is_suppressed(self):
        cfg = SlipMonitorConfig(event_score_threshold=1.0, min_event_steps=3)
        monitor = SlipMonitor(cfg)
        trace = [_record(i, "APPROACH", object_yaw=2.0, eef_yaw=0.0) for i in range(8)]
        # Add a stable lifted tail so the trace is not empty after approach.
        trace.extend(
            _make_lifted_trace(
                lift_start=0, lift_steps=5, object_yaw=0.0, eef_yaw=0.0
            )
        )
        signals = monitor.process_trace(trace)
        # No slip should be reported while the object is not lifted.
        approach_signals = [s for s in signals if s.phase == "APPROACH"]
        assert all(s.no_slip for s in approach_signals)
        assert not any(s.torsional_slip for s in approach_signals)

    def test_vertical_slip_requires_eef_stability(self):
        cfg = SlipMonitorConfig(
            event_score_threshold=1.0,
            min_event_steps=3,
            vertical_drop_threshold=0.0001,
            eef_stability_threshold=0.001,
        )
        monitor = SlipMonitor(cfg)

        def _plateau_then_drop(eef_follows: bool) -> list[dict[str, float | str | int]]:
            trace: list[dict[str, float | str | int]] = [
                _record(0, "APPROACH", object_z=0.2, eef_z=0.2)
            ]
            # Stable lifted plateau.
            for i in range(5):
                trace.append(_record(i + 1, "LIFT", object_z=0.5, eef_z=0.5))
            # Object starts to drop.
            z = 0.5
            for i in range(10):
                eef_z = z if eef_follows else 0.5
                trace.append(_record(i + 6, "LIFT", object_z=z, eef_z=eef_z))
                z -= 0.002
            return trace

        # Gripper follows the object down -> not a slip.
        trace = _plateau_then_drop(eef_follows=True)
        signals = monitor.process_trace(trace)
        assert all(s.no_slip for s in signals)

        # Gripper stays still while object drops -> vertical slip.
        trace2 = _plateau_then_drop(eef_follows=False)
        events = monitor.detect_events(trace2)
        assert len(events) >= 1
        assert events[0]["dominant_type"] == "vertical_slip"

    def test_pose_drift_detected(self):
        cfg = SlipMonitorConfig(
            event_score_threshold=1.0,
            min_event_steps=3,
            position_drift_threshold=0.001,
        )
        monitor = SlipMonitor(cfg)
        trace = _make_lifted_trace(lift_steps=10)
        # After lift, translate the object away from the gripper.
        for rec in trace[5:]:
            rec["object_x"] = 0.05
            rec["object_y"] = 0.05
        events = monitor.detect_events(trace)
        assert len(events) >= 1
        assert events[0]["dominant_type"] == "pose_drift"

    def test_drop_flag(self):
        cfg = SlipMonitorConfig(
            drop_height_threshold=0.22,
            min_lift_height=0.001,
        )
        monitor = SlipMonitor(cfg)
        trace = _make_lifted_trace(lift_steps=5, object_z_final=0.35)
        # Object falls below the drop threshold while still recorded as lifted.
        trace.append(
            _record(
                len(trace),
                "LIFT",
                object_z=0.21,
                eef_z=0.35,
            )
        )
        signals = monitor.process_trace(trace)
        assert signals[-1].drop
        # Drop adds a fixed 1.0 to the score, so it should dominate the event.
        assert signals[-1].slip_score >= 1.0

    def test_min_event_steps_filters_short_spikes(self):
        cfg = SlipMonitorConfig(
            event_score_threshold=1.0,
            min_event_steps=5,
        )
        monitor = SlipMonitor(cfg)
        trace = _make_lifted_trace(lift_steps=12, object_yaw=0.8, eef_yaw=0.0)
        # Zero-out the middle high-yaw region so the spike is only 2 steps.
        for rec in trace[7:9]:
            rec["object_yaw"] = 0.0
        events = monitor.detect_events(trace)
        assert events == []

    def test_event_aggregation_counts_contiguous_steps(self):
        cfg = SlipMonitorConfig(
            event_score_threshold=1.0,
            min_event_steps=3,
        )
        monitor = SlipMonitor(cfg)
        trace = _make_lifted_trace(lift_steps=10, object_yaw=0.8, eef_yaw=0.0)
        events = monitor.detect_events(trace)
        assert len(events) == 1
        assert events[0]["steps"] >= cfg.min_event_steps
        assert events[0]["max_score"] > cfg.event_score_threshold

    def test_yaw_error_increase_component(self):
        cfg = SlipMonitorConfig(
            event_score_threshold=1.0,
            min_event_steps=3,
            yaw_error_increase_threshold=0.05,
        )
        monitor = SlipMonitor(cfg)
        trace = _make_lifted_trace(lift_steps=10, target_yaw=0.0)
        # Object starts aligned and then drifts away from target.
        for i, rec in enumerate(trace[5:]):
            rec["object_yaw"] = i * 0.1
        events = monitor.detect_events(trace)
        assert len(events) >= 1

    def test_config_weights_affect_score(self):
        cfg_low = SlipMonitorConfig(weights={"torsional": 0.1})
        cfg_high = SlipMonitorConfig(weights={"torsional": 1.0})
        trace = _make_lifted_trace(lift_steps=5, object_yaw=0.5, eef_yaw=0.0)
        low = SlipMonitor(cfg_low).process_trace(trace)
        high = SlipMonitor(cfg_high).process_trace(trace)
        # Both should be lifted; compare lifted signals only.
        lifted_low = [s for s in low if s.slip_score > 0 or s.torsional_slip]
        lifted_high = [s for s in high if s.slip_score > 0 or s.torsional_slip]
        assert lifted_high
        assert lifted_high[0].slip_score > lifted_low[0].slip_score

    def test_angle_wrapping_for_torsional_slip(self):
        """A small wrapped yaw difference should not be flagged as torsional slip."""
        cfg = SlipMonitorConfig(torsional_slip_threshold=0.3)
        monitor = SlipMonitor(cfg)
        trace = _make_lifted_trace(
            lift_steps=5, object_yaw=2 * math.pi - 0.05, eef_yaw=0.05
        )
        signals = monitor.process_trace(trace)
        lifted_signals = [s for s in signals if s.phase == "LIFT"]
        assert lifted_signals
        assert all(not s.torsional_slip for s in lifted_signals)
