"""Tests for v1.6 failure classification, anomaly detection, and FBA metrics."""

from __future__ import annotations

import pytest

from rosclaw_darwin.evaluation.progress_metrics import (
    classify_failure_class,
    compute_failure_boundary_advancement,
    detect_metric_anomaly,
)


def test_detect_metric_anomaly_height_delta():
    is_anomaly, tags = detect_metric_anomaly({"object_height_delta": 6.0})
    assert is_anomaly is True
    assert "object_height_delta_anomaly" in tags


def test_detect_metric_anomaly_object_z():
    is_anomaly, tags = detect_metric_anomaly({"object_height_max": 3.5})
    assert is_anomaly is True
    assert "object_z_anomaly" in tags


def test_detect_metric_anomaly_nan():
    is_anomaly, tags = detect_metric_anomaly({"success_rate": float("nan")})
    assert is_anomaly is True
    assert any("nan:" in tag for tag in tags)


def test_detect_metric_anomaly_normal():
    is_anomaly, tags = detect_metric_anomaly({"object_height_delta": 0.2, "object_height_max": 0.5})
    assert is_anomaly is False
    assert tags == []


def test_classify_success():
    assert classify_failure_class({"success": True}) == "success"


def test_classify_workspace_unreachable():
    metrics = {
        "success": False,
        "failure_type": "target_not_reached",
        "phases_reached": ["APPROACH"],
        "grasp_phase_reached": False,
        "eef_to_object_distance_min": 0.2,
        "object_y_initial": 0.08,
    }
    trace = [{"object_y": 0.08, "phase": "APPROACH"}]
    assert classify_failure_class(metrics, trace=trace) == "workspace_unreachable"


def test_classify_approach_collision():
    metrics = {
        "success": False,
        "failure_type": "target_not_reached",
        "phases_reached": ["APPROACH"],
        "grasp_phase_reached": False,
        "eef_to_object_distance_min": 0.2,
        "object_y_initial": 0.0,
    }
    assert classify_failure_class(metrics) == "approach_collision"


def test_classify_grasp_failed():
    metrics = {
        "success": False,
        "failure_type": "object_not_lifted",
        "phases_reached": ["APPROACH", "DESCEND", "GRASP"],
        "grasp_phase_reached": True,
        "lift_phase_reached": False,
        "object_height_delta": 0.0,
    }
    assert classify_failure_class(metrics) == "grasp_failed"


def test_classify_large_yaw_slip():
    metrics = {
        "success": False,
        "failure_type": "target_not_reached_after_lift",
        "phases_reached": ["APPROACH", "DESCEND", "GRASP", "LIFT"],
        "grasp_phase_reached": True,
        "lift_phase_reached": True,
        "object_height_delta": 0.2,
        "target_yaw": 1.57,
    }
    trace = [{"target_yaw": 1.57, "object_yaw_error": 0.6, "phase": "HOLD"}]
    assert classify_failure_class(metrics, trace=trace) == "large_yaw_slip"


def test_classify_orientation_not_achieved():
    metrics = {
        "success": False,
        "failure_type": "target_not_reached_after_lift",
        "phases_reached": ["APPROACH", "DESCEND", "GRASP", "LIFT"],
        "grasp_phase_reached": True,
        "lift_phase_reached": True,
        "object_height_delta": 0.2,
        "target_yaw": 0.5,
    }
    trace = [{"target_yaw": 0.5, "object_yaw_error": 0.6, "phase": "HOLD"}]
    assert classify_failure_class(metrics, trace=trace) == "orientation_not_achieved"


def test_classify_hold_instability():
    metrics = {
        "success": False,
        "failure_type": "target_not_reached_after_lift",
        "phases_reached": ["APPROACH", "DESCEND", "GRASP", "LIFT"],
        "grasp_phase_reached": True,
        "lift_phase_reached": True,
        "object_height_delta": 0.2,
        "target_yaw": 0.5,
    }
    trace = [{"target_yaw": 0.5, "object_yaw_error": 0.1, "phase": "HOLD"}]
    assert classify_failure_class(metrics, trace=trace) == "hold_instability"


def test_classify_physics_anomaly():
    metrics = {"object_height_delta": 6.0}
    assert classify_failure_class(metrics) == "physics_anomaly"


def test_classify_metric_parser_error():
    metrics = {"success_rate": float("nan")}
    assert classify_failure_class(metrics) == "metric_parser_error"


def test_compute_failure_boundary_advancement():
    baseline = [2, 2, 3]  # DESCEND, DESCEND, GRASP
    condition = [3, 4, 4]  # GRASP, LIFT, LIFT
    result = compute_failure_boundary_advancement(baseline, condition)
    assert result["baseline_mean_phase_score"] == pytest.approx(7 / 3, abs=1e-4)
    assert result["condition_mean_phase_score"] == pytest.approx(11 / 3, abs=1e-4)
    assert result["fba"] == pytest.approx(4 / 3, abs=1e-4)
    assert "phase_score_mapping" in result
