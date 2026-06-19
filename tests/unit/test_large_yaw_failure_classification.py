"""Unit tests for large-yaw failure classification categories."""

import math

from rosclaw_darwin.evaluation.yaw_coupling import classify_large_yaw_failure


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


def test_post_lift_slip():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (1.5, 1.5, 0.15, "LIFT"),
            (1.55, 1.0, 0.25, "LIFT"),
            (1.55, 0.9, 0.30, "HOLD"),
        ],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "post_lift_slip"
    assert diag["torsional_slip_detected"]


def test_align_induced_slip():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (1.5, 1.5, 0.15, "LIFT"),
            (1.55, 1.5, 0.25, "ALIGN"),
            (1.55, 0.8, 0.30, "ALIGN"),
        ],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "align_induced_slip"
    assert diag["phase_of_first_slip"] == "ALIGN"


def test_torsional_slip_generic():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (1.5, 1.5, 0.15, "LIFT"),
            (1.55, 1.0, 0.30, "GRASP"),
            (1.55, 0.9, 0.30, "HOLD"),
        ],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "torsional_slip"


def test_not_lifted():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (0.0, 0.0, 0.05, "DESCEND"),
            (0.0, 0.0, 0.05, "GRASP"),
        ],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "not_lifted"


def test_success():
    trace = _make_trace(
        math.pi / 2,
        [
            (0.0, 0.0, 0.05, "APPROACH"),
            (1.5, 1.5, 0.15, "LIFT"),
            (1.55, 1.55, 0.30, "HOLD"),
        ],
    )
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] == "success"
    assert diag["orientation_achieved"]
