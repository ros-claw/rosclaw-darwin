"""Yaw-coupling diagnostics for large-yaw goal_pose failures.

The large-yaw matrix showed that the object is lifted but ends up with the wrong
yaw.  This module separates three possible mechanisms:

1. EEF yaw never reaches the target (eef_yaw_failure).
2. EEF yaw reaches target but object yaw does not follow (object_not_coupled).
3. Object yaw follows initially but then slips relative to the EEF (torsional_slip).
"""

from __future__ import annotations

import math
from typing import Any


def _angle_diff(target: float, current: float) -> float:
    diff = target - current
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return diff


def _get(record: dict[str, Any], key: str) -> float | None:
    val = record.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None


def compute_yaw_metrics(
    trace: list[dict[str, Any]],
    orientation_threshold: float = 0.5,
) -> dict[str, Any]:
    """Compute end-effector / object yaw metrics from a goal_pose trace."""
    if not trace:
        return {
            "eef_yaw_final_error": None,
            "object_yaw_final_error": None,
            "orientation_achieved": False,
            "lifted": False,
            "max_object_z": None,
        }

    first = trace[0]
    last = trace[-1]

    target_yaw = _get(last, "target_yaw") or _get(first, "target_yaw")
    eef_yaw_final = _get(last, "eef_yaw")
    object_yaw_final = _get(last, "object_yaw")
    max_object_z = max((_get(r, "object_z") for r in trace if _get(r, "object_z") is not None), default=None)
    lifted = max_object_z is not None and max_object_z > (_get(first, "object_z") or 0.0) + 0.03

    eef_yaw_final_error = None
    object_yaw_final_error = None
    orientation_achieved = False
    if target_yaw is not None:
        if eef_yaw_final is not None:
            eef_yaw_final_error = abs(_angle_diff(target_yaw, eef_yaw_final))
        if object_yaw_final is not None:
            object_yaw_final_error = abs(_angle_diff(target_yaw, object_yaw_final))
            orientation_achieved = object_yaw_final_error < orientation_threshold

    return {
        "eef_yaw_final_error": eef_yaw_final_error,
        "object_yaw_final_error": object_yaw_final_error,
        "orientation_achieved": orientation_achieved,
        "lifted": lifted,
        "max_object_z": max_object_z,
        "target_yaw": target_yaw,
        "eef_yaw_final": eef_yaw_final,
        "object_yaw_final": object_yaw_final,
    }


def compute_yaw_coupling_score(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a simplified yaw-coupling score during lifted phases.

    The score is ``|object_yaw_change| / max(|eef_yaw_change|, eps)`` computed
    over contiguous windows where the object is clearly lifted (object_z > 0.1).
    A score near 1 means the object yaw tracks the EEF yaw; near 0 means the
    object does not rotate with the gripper.
    """
    lifted_steps = [r for r in trace if (_get(r, "object_z") or 0.0) > 0.1]
    if len(lifted_steps) < 2:
        return {"yaw_coupling_score": None, "coupling_windows": 0}

    eef_changes: list[float] = []
    object_changes: list[float] = []
    for prev, cur in zip(lifted_steps[:-1], lifted_steps[1:]):
        eef_prev = _get(prev, "eef_yaw")
        eef_cur = _get(cur, "eef_yaw")
        obj_prev = _get(prev, "object_yaw")
        obj_cur = _get(cur, "object_yaw")
        if eef_prev is None or eef_cur is None or obj_prev is None or obj_cur is None:
            continue
        eef_changes.append(abs(_angle_diff(eef_cur, eef_prev)))
        object_changes.append(abs(_angle_diff(obj_cur, obj_prev)))

    if not eef_changes:
        return {"yaw_coupling_score": None, "coupling_windows": 0}

    total_eef = sum(eef_changes)
    total_obj = sum(object_changes)
    eps = 1e-6
    score = total_obj / max(total_eef, eps)
    return {
        "yaw_coupling_score": float(score),
        "total_eef_yaw_change": float(total_eef),
        "total_object_yaw_change": float(total_obj),
        "coupling_windows": len(eef_changes),
    }


def detect_torsional_slip(
    trace: list[dict[str, Any]],
    slip_threshold: float = 0.3,
) -> dict[str, Any]:
    """Detect in-hand torsional slip: object yaw diverges from eef yaw after grasp.

    Returns the step/phase where the divergence first exceeds ``slip_threshold``
    and the maximum divergence observed.
    """
    if not trace:
        return {
            "torsional_slip_detected": False,
            "phase_of_first_slip": None,
            "step_of_first_slip": None,
            "object_height_at_first_slip": None,
            "max_object_eef_yaw_delta": None,
        }

    first = trace[0]
    initial_object_eef_delta: float | None = None
    obj0 = _get(first, "object_yaw")
    eef0 = _get(first, "eef_yaw")
    if obj0 is not None and eef0 is not None:
        initial_object_eef_delta = _angle_diff(obj0, eef0)

    slip_step: int | None = None
    slip_phase: str | None = None
    slip_height: float | None = None
    max_delta = 0.0
    for r in trace:
        obj_yaw = _get(r, "object_yaw")
        eef_yaw = _get(r, "eef_yaw")
        if obj_yaw is None or eef_yaw is None:
            continue
        current_delta = _angle_diff(obj_yaw, eef_yaw)
        if initial_object_eef_delta is not None:
            delta = abs(_angle_diff(current_delta, initial_object_eef_delta))
        else:
            delta = abs(current_delta)
        max_delta = max(max_delta, delta)
        if slip_step is None and delta > slip_threshold:
            slip_step = int(r.get("step", 0))
            slip_phase = str(r.get("phase", "UNKNOWN"))
            slip_height = _get(r, "object_z")

    return {
        "torsional_slip_detected": slip_step is not None,
        "phase_of_first_slip": slip_phase,
        "step_of_first_slip": slip_step,
        "object_height_at_first_slip": slip_height,
        "max_object_eef_yaw_delta": float(max_delta),
    }


def classify_large_yaw_failure(
    trace: list[dict[str, Any]],
    orientation_threshold: float = 0.5,
    eef_yaw_error_threshold: float = 0.5,
    coupling_threshold: float = 0.3,
) -> dict[str, Any]:
    """Classify the mechanism of a large-yaw episode."""
    metrics = compute_yaw_metrics(trace, orientation_threshold=orientation_threshold)
    coupling = compute_yaw_coupling_score(trace)
    slip = detect_torsional_slip(trace)

    category = "unknown"
    if not metrics["lifted"]:
        category = "not_lifted"
    elif metrics["orientation_achieved"]:
        category = "success"
    elif metrics["eef_yaw_final_error"] is not None and metrics["eef_yaw_final_error"] > eef_yaw_error_threshold:
        category = "eef_yaw_failure"
    elif slip["torsional_slip_detected"]:
        if slip["phase_of_first_slip"] in ("LIFT", "REORIENT"):
            category = "post_lift_slip"
        elif slip["phase_of_first_slip"] in ("ALIGN",):
            category = "align_induced_slip"
        else:
            category = "torsional_slip"
    elif (coupling["yaw_coupling_score"] is not None and coupling["yaw_coupling_score"] < coupling_threshold):
        category = "object_not_coupled"
    else:
        category = "torsional_slip"

    return {
        "category": category,
        **metrics,
        **coupling,
        **slip,
    }
