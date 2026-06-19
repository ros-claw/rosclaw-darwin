"""Unit tests for yaw-coupling diagnostics."""

import math

from rosclaw_darwin.evaluation.yaw_coupling import (
    classify_large_yaw_failure,
    compute_yaw_coupling_score,
    compute_yaw_metrics,
    detect_torsional_slip,
)


def _make_trace(target_yaw: float, sequence: list[tuple[float, float, float, str]]) -> list[dict]:
    """Build a trace from (eef_yaw, object_yaw, object_z, phase) tuples."""
    return [
        {
            "step": i,
            "target_yaw": target_yaw,
            "eef_yaw": eef,
            "object_yaw": obj,
            "object_z": z,
            "phase": phase,
        }
        for i, (eef, obj, z, phase) in enumerate(sequence)
    ]


def test_yaw_metrics_success():
    trace = _make_trace(
        math.pi / 2,
        [(0.0, 0.0, 0.05, "APPROACH"), (1.5, 1.48, 0.15, "LIFT"), (1.55, 1.55, 0.30, "HOLD")],
    )
    metrics = compute_yaw_metrics(trace, orientation_threshold=0.2)
    assert metrics["lifted"]
    assert metrics["orientation_achieved"]
    assert metrics["object_yaw_final_error"] < 0.2


def test_yaw_metrics_eef_failure():
    trace = _make_trace(
        math.pi / 2,
        [(0.0, 0.0, 0.05, "APPROACH"), (0.1, 0.1, 0.15, "LIFT"), (0.1, 0.1, 0.30, "HOLD")],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "eef_yaw_failure"


def test_yaw_metrics_object_not_coupled():
    trace = _make_trace(
        math.pi / 2,
        [(1.57, 0.0, 0.05, "APPROACH"), (1.57, 0.0, 0.15, "LIFT"), (1.57, 0.0, 0.30, "HOLD")],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "object_not_coupled"


def test_torsional_slip_detected():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (1.5, 1.5, 0.15, "LIFT"),
            (1.55, 1.0, 0.30, "ALIGN"),
            (1.55, 0.9, 0.30, "HOLD"),
        ],
    )
    slip = detect_torsional_slip(trace)
    assert slip["torsional_slip_detected"]
    assert slip["phase_of_first_slip"] == "ALIGN"


def test_yaw_coupling_score_perfect():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (0.5, 0.5, 0.15, "LIFT"),
            (1.0, 1.0, 0.20, "LIFT"),
            (1.5, 1.5, 0.30, "HOLD"),
        ],
    )
    coupling = compute_yaw_coupling_score(trace)
    assert coupling["yaw_coupling_score"] is not None
    assert coupling["yaw_coupling_score"] > 0.95


def test_yaw_coupling_score_zero():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (0.5, 0.0, 0.15, "LIFT"),
            (1.5, 0.0, 0.30, "HOLD"),
        ],
    )
    coupling = compute_yaw_coupling_score(trace)
    assert coupling["yaw_coupling_score"] == 0.0
