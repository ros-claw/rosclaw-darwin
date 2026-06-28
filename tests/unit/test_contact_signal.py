"""Unit tests for the ContactSignal abstraction."""

from __future__ import annotations

from rosclaw_darwin.evaluation.contact_signal import ContactSignal, ContactSignalProvider


def test_no_contact_classification():
    provider = ContactSignalProvider()
    sig = provider.compute_from_kinematics(
        {
            "step": 0,
            "phase": "GRASP",
            "gripper_pos": 0.09,
            "object_pos": [0.35, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    assert sig.contact_state == "no_contact"
    assert sig.contact_confidence > 0


def test_likely_contact_classification():
    provider = ContactSignalProvider(gripper_close_threshold=0.012)
    sig = provider.compute_from_kinematics(
        {
            "step": 5,
            "phase": "GRASP",
            "gripper_pos": 0.038,
            "object_pos": [0.35, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    assert sig.contact_state == "likely_contact"


def test_weak_contact_no_lift_classification():
    provider = ContactSignalProvider(gripper_close_threshold=0.012)
    sig = provider.compute_from_kinematics(
        {
            "step": 5,
            "phase": "GRASP",
            "gripper_pos": 0.01,
            "object_pos": [0.35, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    assert sig.contact_state == "weak_contact_no_lift"


def test_pushed_away_classification():
    provider = ContactSignalProvider()
    # Seed the grasp-start reference with the first frame.
    provider.compute_from_kinematics(
        {
            "step": 0,
            "phase": "GRASP",
            "gripper_pos": 0.05,
            "object_pos": [0.35, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    sig = provider.compute_from_kinematics(
        {
            "step": 1,
            "phase": "GRASP",
            "gripper_pos": 0.05,
            "object_pos": [0.32, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    assert sig.contact_state == "pushed_away"


def test_missing_observation_returns_unknown():
    provider = ContactSignalProvider()
    sig = provider.compute_from_kinematics({"step": 0, "phase": "GRASP"})
    assert sig.contact_state == "unknown"
    assert sig.reason == "missing_observation"


def test_gripper_joint_source_close_command_unmet():
    provider = ContactSignalProvider()
    sig = provider.compute_from_gripper_joint(
        {"step": 0, "phase": "GRASP", "gripper_pos": 0.038, "gripper_cmd": 0.0}
    )
    assert sig.source == "gripper_joint"
    assert sig.contact_state == "likely_contact"
    assert sig.gripper_width_error is not None


def test_gripper_joint_source_close_command_met():
    provider = ContactSignalProvider()
    sig = provider.compute_from_gripper_joint(
        {"step": 0, "phase": "GRASP", "gripper_pos": 0.012, "gripper_cmd": 0.01}
    )
    assert sig.contact_state == "weak_contact_no_lift"


def test_merge_sources_prefers_high_confidence():
    provider = ContactSignalProvider()
    kin = provider.compute_from_kinematics(
        {
            "step": 0,
            "phase": "GRASP",
            "gripper_pos": 0.038,
            "object_pos": [0.35, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    joint = provider.compute_from_gripper_joint(
        {"step": 0, "phase": "GRASP", "gripper_pos": 0.038, "gripper_cmd": 0.0}
    )
    merged = ContactSignalProvider.merge_sources([kin, joint])
    assert merged is not None
    assert merged.contact_state in (kin.contact_state, joint.contact_state)


def test_merge_sources_conflict_downgrades_to_unknown():
    kin = ContactSignal(
        step=0,
        phase="GRASP",
        source="kinematics",
        contact_confidence=0.8,
        contact_state="likely_contact",
    )
    joint = ContactSignal(
        step=0,
        phase="GRASP",
        source="gripper_joint",
        contact_confidence=0.75,
        contact_state="no_contact",
    )
    merged = ContactSignalProvider.merge_sources([kin, joint])
    assert merged is not None
    assert merged.contact_state == "unknown"
    assert "conflict" in (merged.reason or "")


def test_process_trace_preserves_length():
    provider = ContactSignalProvider()
    trace = [
        {"step": i, "phase": "GRASP", "gripper_pos": 0.05 - i * 0.001, "object_pos": [0.35, 0.0, 0.025], "eef_pos": [0.35, 0.0, 0.03]}
        for i in range(10)
    ]
    signals = provider.process_trace(trace)
    assert len(signals) == len(trace)
    assert all(isinstance(s, ContactSignal) for s in signals)


def test_reset_clears_grasp_start():
    provider = ContactSignalProvider()
    provider.compute_from_kinematics(
        {
            "step": 0,
            "phase": "GRASP",
            "gripper_pos": 0.05,
            "object_pos": [0.35, 0.0, 0.025],
            "eef_pos": [0.35, 0.0, 0.03],
        }
    )
    assert provider._grasp_start_object_pos is not None
    provider.reset()
    assert provider._grasp_start_object_pos is None
    assert provider._grasp_start_eef_pos is None
