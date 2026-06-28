"""Unit tests for the grip-quality monitor."""

import pytest

from rosclaw_darwin.evaluation.grip_quality import (
    GripQualityMonitor,
    GripQualityMonitorConfig,
    GripQualitySignal,
)


def make_record(
    step: int = 0,
    phase: str = "GRASP",
    object_z: float | None = 0.025,
    eef_z: float | None = 0.03,
    gripper_pos: float | None = 0.02,
) -> dict:
    return {
        "step": step,
        "phase": phase,
        "object_z": object_z,
        "eef_z": eef_z,
        "gripper_pos": gripper_pos,
    }


def test_signal_properties():
    sig = GripQualitySignal(
        step=0,
        phase="LIFT_VERIFY",
        object_z_at_grasp=0.021,
        gripper_width_after_close=0.038,
        object_height_response_to_lift=0.003,
        object_follows_eef_score=0.002,
        grip_quality_score=0.0,
        grip_failure_risk=1.0,
        trigger_micro_recovery=True,
        reason="test",
    )
    assert sig.low_object_z
    assert sig.gripper_too_open
    assert sig.weak_lift_response


def test_normal_grasp_does_not_trigger():
    monitor = GripQualityMonitor()
    trace = []
    for i in range(20):
        trace.append(make_record(step=i, phase="GRASP", object_z=0.026, gripper_pos=0.02))
    signals = monitor.process_trace(trace)
    assert not any(s.trigger_micro_recovery for s in signals)


def test_seed24_signature_triggers_in_lift_verify():
    cfg = GripQualityMonitorConfig(min_lift_verify_steps_for_response=1)
    monitor = GripQualityMonitor(cfg)
    trace = []
    for i in range(15):
        trace.append(make_record(step=i, phase="GRASP", object_z=0.021, gripper_pos=0.038))
    for i in range(5):
        trace.append(
            make_record(
                step=15 + i,
                phase="LIFT_VERIFY",
                object_z=0.0212,
                eef_z=0.027,
                gripper_pos=0.038,
            )
        )
    signals = monitor.process_trace(trace)
    trigger_signals = [s for s in signals if s.trigger_micro_recovery]
    assert len(trigger_signals) >= 1
    assert trigger_signals[0].phase == "LIFT_VERIFY"
    assert trigger_signals[0].reason is not None


def test_trigger_locked_after_first_trigger():
    cfg = GripQualityMonitorConfig(lock_after_trigger=True)
    monitor = GripQualityMonitor(cfg)
    trace = []
    for i in range(15):
        trace.append(make_record(step=i, phase="GRASP", object_z=0.021, gripper_pos=0.038))
    for i in range(10):
        trace.append(
            make_record(
                step=15 + i,
                phase="LIFT_VERIFY",
                object_z=0.0212,
                eef_z=0.027,
                gripper_pos=0.038,
            )
        )
    signals = monitor.process_trace(trace)
    assert sum(s.trigger_micro_recovery for s in signals) == 1


def test_no_trigger_outside_allowed_phases():
    cfg = GripQualityMonitorConfig(min_lift_verify_steps_for_response=1)
    monitor = GripQualityMonitor(cfg)
    trace = []
    for i in range(15):
        trace.append(make_record(step=i, phase="GRASP", object_z=0.021, gripper_pos=0.038))
    for i in range(5):
        trace.append(
            make_record(
                step=15 + i,
                phase="REORIENT",
                object_z=0.0212,
                eef_z=0.027,
                gripper_pos=0.038,
            )
        )
    signals = monitor.process_trace(trace)
    assert not any(s.trigger_micro_recovery for s in signals)


def test_recovery_trigger_phases_are_configurable():
    """The policy restricts three-way triggers to GRASP/CONTACT_VERIFY only."""
    cfg = GripQualityMonitorConfig(
        min_lift_verify_steps_for_response=1,
        recovery_trigger_phases={"GRASP", "CONTACT_VERIFY"},
    )
    monitor = GripQualityMonitor(cfg)
    trace = []
    for i in range(15):
        trace.append(make_record(step=i, phase="GRASP", object_z=0.021, gripper_pos=0.038))
    for i in range(5):
        trace.append(
            make_record(
                step=15 + i,
                phase="LIFT_VERIFY",
                object_z=0.0212,
                eef_z=0.027,
                gripper_pos=0.038,
            )
        )
    signals = monitor.process_trace(trace)
    assert not any(s.trigger_micro_recovery for s in signals)


def test_grasp_risk_without_lift_response():
    """In GRASP we can only observe low_z + gripper_too_open, so risk is 2/3."""
    cfg = GripQualityMonitorConfig()
    monitor = GripQualityMonitor(cfg)
    trace = [make_record(step=i, phase="GRASP", object_z=0.021, gripper_pos=0.038) for i in range(15)]
    signals = monitor.process_trace(trace)
    post_width = [s for s in signals if s.gripper_width_after_close is not None]
    assert all(s.grip_failure_risk == pytest.approx(0.6667) for s in post_width)
    assert not any(s.trigger_micro_recovery for s in signals)
