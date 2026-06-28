#!/usr/bin/env python3
"""Unit tests for contact signal reliability audit helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from rosclaw_darwin.evaluation.contact_signal import ContactSignalProvider
from scripts.diagnostics.run_contact_signal_reliability_audit import (
    REQUIRED_PHASES,
    _audit_trace,
    _extract_seed_from_dir,
    _normalize_phase,
)


def test_normalize_phase_maps_lift_verify():
    assert _normalize_phase("LIFT_VERIFY") == "LIFT"


def test_normalize_phase_maps_recovery():
    assert _normalize_phase("RECOVERY_LOWER") == "RECOVERY"
    assert _normalize_phase("RECOVER") == "RECOVERY"


def test_normalize_phase_keeps_required():
    for phase in REQUIRED_PHASES:
        assert _normalize_phase(phase) == phase


def test_normalize_phase_returns_none_for_unknown():
    assert _normalize_phase("APPROACH") is None
    assert _normalize_phase("DESCEND") is None


def test_extract_seed_from_dir():
    assert _extract_seed_from_dir(Path("seed_024")) == 24
    assert _extract_seed_from_dir(Path("seed000")) == 0
    assert _extract_seed_from_dir(Path("seed-105")) == 105
    assert _extract_seed_from_dir(Path("not_a_seed")) is None


def test_audit_trace_counts_states_per_phase():
    trace = [
        {"step": 0, "phase": "GRASP", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.1], "eef_pos": [0.0, 0.0, 0.1]},
        {"step": 1, "phase": "GRASP", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.1], "eef_pos": [0.0, 0.0, 0.1]},
        {"step": 2, "phase": "LIFT_VERIFY", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.2], "eef_pos": [0.0, 0.0, 0.2]},
        {"step": 3, "phase": "HOLD", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.2], "eef_pos": [0.0, 0.0, 0.2]},
        {"step": 4, "phase": "CONTACT_VERIFY", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.2], "eef_pos": [0.0, 0.0, 0.2], "contact_proxy": "likely_contact"},
    ]
    provider = ContactSignalProvider()
    result = _audit_trace(trace, provider)

    assert result["total_frames_audited"] == 5
    assert result["phase_metrics"]["GRASP"]["steps"] == 2
    assert result["phase_metrics"]["LIFT"]["steps"] == 1
    assert result["phase_metrics"]["HOLD"]["steps"] == 1
    assert result["phase_metrics"]["CONTACT_VERIFY"]["steps"] == 1

    # All frames with object positions should produce a non-unknown state.
    for phase in ("GRASP", "LIFT", "HOLD", "CONTACT_VERIFY"):
        assert result["phase_metrics"][phase]["coverage_rate"] == 1.0
        assert result["phase_metrics"][phase]["missing_signal_rate"] == 0.0


def test_audit_trace_prefers_trace_state():
    trace = [
        {"step": 0, "phase": "GRASP", "contact_state": "weak_contact_no_lift", "contact_confidence": 0.6},
    ]
    provider = ContactSignalProvider()
    result = _audit_trace(trace, provider)
    assert result["phase_metrics"]["GRASP"]["state_distribution"]["weak_contact_no_lift"] == 1


def test_audit_trace_ignores_non_required_phases():
    trace = [
        {"step": 0, "phase": "APPROACH"},
        {"step": 1, "phase": "DESCEND"},
    ]
    provider = ContactSignalProvider()
    result = _audit_trace(trace, provider)
    assert result["total_frames_audited"] == 0


def test_audit_trace_legacy_proxy_agreement_only_in_contact_verify():
    trace = [
        {"step": 0, "phase": "GRASP", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.1], "eef_pos": [0.0, 0.0, 0.1], "contact_proxy": "likely_contact"},
        {"step": 1, "phase": "CONTACT_VERIFY", "gripper_pos": 0.04, "object_pos": [0.0, 0.0, 0.1], "eef_pos": [0.0, 0.0, 0.1], "contact_proxy": "likely_contact"},
    ]
    provider = ContactSignalProvider()
    result = _audit_trace(trace, provider)
    assert result["phase_metrics"]["GRASP"]["legacy_proxy_compared"] == 0
    assert result["phase_metrics"]["CONTACT_VERIFY"]["legacy_proxy_compared"] == 1
    assert result["phase_metrics"]["CONTACT_VERIFY"]["legacy_proxy_agreement_rate"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
