"""Slip forensics helpers for post-lift goal_pose failures.

These functions operate on step-level traces produced by
``HeuristicServoGoalPosePolicy``.  They are intentionally dependency-free so
that they can run on the host inside reports, tests, and dashboard loaders.
"""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _angle_diff(target: float, current: float) -> float:
    diff = target - current
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return diff


def _point_distance(r: dict[str, Any], prefix_a: str, prefix_b: str) -> float | None:
    a = (_to_float(r.get(f"{prefix_a}_x")), _to_float(r.get(f"{prefix_a}_y")), _to_float(r.get(f"{prefix_a}_z")))
    b = (_to_float(r.get(f"{prefix_b}_x")), _to_float(r.get(f"{prefix_b}_y")), _to_float(r.get(f"{prefix_b}_z")))
    if None in a or None in b:
        return None
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _find_phase_start(trace: list[dict[str, Any]], phase: str) -> int | None:
    for i, r in enumerate(trace):
        if r.get("phase") == phase:
            return i
    return None


def compute_lift_drop_forensics(
    trace: list[dict[str, Any]],
    lift_threshold: float = 0.03,
    drop_threshold: float = 0.05,
) -> dict[str, Any]:
    """Compute lift/drop timings from a single episode trace.

    Returns whether the object was lifted, the maximum height reached, the step
    at which the drop was first detected, and the phase active at that step.
    """
    if not trace:
        return {
            "lifted": False,
            "initial_object_z": None,
            "max_object_z": None,
            "step_of_max_height": None,
            "object_dropped": False,
            "drop_step": None,
            "drop_phase": None,
            "final_object_z": None,
        }

    object_zs = [_to_float(r.get("object_z")) for r in trace]
    initial_z = next((z for z in object_zs if z is not None), None)
    if initial_z is None:
        return {
            "lifted": False,
            "initial_object_z": None,
            "max_object_z": None,
            "step_of_max_height": None,
            "object_dropped": False,
            "drop_step": None,
            "drop_phase": None,
            "final_object_z": None,
        }

    max_z = initial_z
    step_of_max = 0
    for i, z in enumerate(object_zs):
        if z is not None and z > max_z:
            max_z = z
            step_of_max = i

    lifted = max_z - initial_z > lift_threshold
    final_z = object_zs[-1]

    drop_step: int | None = None
    drop_phase: str | None = None
    if lifted:
        for i in range(step_of_max, len(trace)):
            z = object_zs[i]
            if z is not None and z < max_z - drop_threshold:
                drop_step = i
                drop_phase = str(trace[i].get("phase", "UNKNOWN"))
                break
        # If the trace ended below the drop threshold, mark the final step.
        if drop_step is None and final_z is not None and final_z < max_z - drop_threshold:
            drop_step = len(trace) - 1
            drop_phase = str(trace[-1].get("phase", "UNKNOWN"))

    object_dropped = drop_step is not None

    return {
        "lifted": lifted,
        "initial_object_z": initial_z,
        "max_object_z": max_z,
        "step_of_max_height": step_of_max,
        "object_dropped": object_dropped,
        "drop_step": drop_step,
        "drop_phase": drop_phase,
        "final_object_z": final_z,
    }


def compute_torsional_slip_forensics(
    trace: list[dict[str, Any]],
    slip_threshold: float = 0.3,
    grasp_phase: str = "GRASP",
    grasp_settle_steps: int = 10,
) -> dict[str, Any]:
    """Detect in-hand torsional slip and locate it in the episode.

    Computes the object-to-EEF yaw delta over time and reports the first step
    where it grows beyond ``slip_threshold`` relative to the initial grasped
    delta.  The initial delta is measured after the GRASP phase has settled so
    that pre-grasp orientation differences are not treated as slip.
    """
    if not trace:
        return {
            "torsional_slip_detected": False,
            "phase_of_first_slip": None,
            "step_of_first_slip": None,
            "object_height_at_first_slip": None,
            "max_object_eef_yaw_delta": None,
        }

    grasp_start = _find_phase_start(trace, grasp_phase)
    if grasp_start is None:
        grasp_start = 0
    settle_idx = min(grasp_start + grasp_settle_steps, len(trace) - 1)
    first = trace[settle_idx]

    obj0 = _to_float(first.get("object_yaw"))
    eef0 = _to_float(first.get("eef_yaw"))
    initial_delta: float | None = None
    if obj0 is not None and eef0 is not None:
        initial_delta = _angle_diff(obj0, eef0)

    slip_step: int | None = None
    slip_phase: str | None = None
    slip_height: float | None = None
    max_delta = 0.0
    for r in trace[settle_idx:]:
        obj_yaw = _to_float(r.get("object_yaw"))
        eef_yaw = _to_float(r.get("eef_yaw"))
        if obj_yaw is None or eef_yaw is None:
            continue
        current_delta = _angle_diff(obj_yaw, eef_yaw)
        if initial_delta is not None:
            delta = abs(_angle_diff(current_delta, initial_delta))
        else:
            delta = abs(current_delta)
        max_delta = max(max_delta, delta)
        if slip_step is None and delta > slip_threshold:
            slip_step = int(r.get("step", 0))
            slip_phase = str(r.get("phase", "UNKNOWN"))
            slip_height = _to_float(r.get("object_z"))

    return {
        "torsional_slip_detected": slip_step is not None,
        "phase_of_first_slip": slip_phase,
        "step_of_first_slip": slip_step,
        "object_height_at_first_slip": slip_height,
        "max_object_eef_yaw_delta": float(max_delta),
    }


def compute_gripper_forensics(
    trace: list[dict[str, Any]],
    grasp_phase: str = "GRASP",
    release_delta: float = 0.01,
    drop_step: int | None = None,
    blocked_threshold: float = 0.035,
) -> dict[str, Any]:
    """Compute gripper-related statistics after the GRASP phase starts.

    The key quantity for seed-24 style failures is whether the fingers actually
    blocked on the cube while it was lifted.  A ``gripper_pos_min`` above
    ``blocked_threshold`` during the lifted phase means the gripper never
    squeezed the object, which explains why it slips later.

    Release detection looks for a sustained opening (``release_delta`` above the
    blocked minimum) before the drop, because the gripper closing after the
    object has already fallen is an effect, not a cause.
    """
    grasp_start = _find_phase_start(trace, grasp_phase)
    if grasp_start is None:
        return {
            "gripper_pos_min": None,
            "gripper_pos_min_while_lifted": None,
            "gripper_pos_mean_after_grasp": None,
            "gripper_blocked": False,
            "gripper_release_detected": False,
            "gripper_release_step": None,
        }

    end_step = drop_step if drop_step is not None else len(trace)
    # Max height reached before the drop, so we can restrict "lifted" steps to
    # those very close to the apex and exclude the onset of the drop itself.
    object_zs = [_to_float(r.get("object_z")) for r in trace[grasp_start:end_step]]
    max_z = max((z for z in object_zs if z is not None), default=None)
    height_floor = max_z - 0.01 if max_z is not None else None

    lifted_gripper_values: list[float] = []
    all_gripper_values: list[float] = []
    for i, r in enumerate(trace[grasp_start:end_step]):
        g = _to_float(r.get("gripper_pos"))
        z = _to_float(r.get("object_z"))
        if g is None:
            continue
        all_gripper_values.append(g)
        if height_floor is not None and z is not None and z >= height_floor:
            lifted_gripper_values.append(g)

    if not all_gripper_values:
        return {
            "gripper_pos_min": None,
            "gripper_pos_min_while_lifted": None,
            "gripper_pos_mean_after_grasp": None,
            "gripper_blocked": False,
            "gripper_release_detected": False,
            "gripper_release_step": None,
        }

    # Prefer the lifted-phase minimum; fall back to all pre-drop values if the
    # object never got near its max height before dropping.
    lifted_min = min(lifted_gripper_values) if lifted_gripper_values else None
    all_min = min(all_gripper_values)
    if lifted_min is None:
        lifted_min = all_min

    mean_g = sum(all_gripper_values) / len(all_gripper_values)
    blocked = lifted_min is not None and lifted_min <= blocked_threshold

    # Release detection only makes sense if the gripper was blocked.  Require
    # the opening to persist for several steps before the drop.
    release_step: int | None = None
    if blocked:
        consecutive = 0
        for i, r in enumerate(trace[grasp_start:end_step]):
            g = _to_float(r.get("gripper_pos"))
            if g is not None and g > lifted_min + release_delta:
                consecutive += 1
                if consecutive >= 3:
                    release_step = grasp_start + i - 2
                    break
            else:
                consecutive = 0

    return {
        "gripper_pos_min": all_min,
        "gripper_pos_min_while_lifted": lifted_min,
        "gripper_pos_mean_after_grasp": mean_g,
        "gripper_blocked": blocked,
        "gripper_release_detected": release_step is not None,
        "gripper_release_step": release_step,
    }


def compute_vertical_velocity_forensics(
    trace: list[dict[str, Any]],
    window: int = 5,
) -> dict[str, Any]:
    """Compute per-step object vertical velocity and peak values.

    Uses a simple finite difference.  Positive values mean upward motion.
    """
    object_zs = [_to_float(r.get("object_z")) for r in trace]
    velocities: list[float | None] = [None] * len(object_zs)
    for i in range(1, len(object_zs)):
        prev = object_zs[i - 1]
        cur = object_zs[i]
        if prev is not None and cur is not None:
            velocities[i] = cur - prev

    valid_velocities = [v for v in velocities if v is not None]
    max_up = max(valid_velocities) if valid_velocities else None
    max_down = min(valid_velocities) if valid_velocities else None

    # Smoothed velocity at each step using a centered window.
    smoothed: list[float | None] = [None] * len(velocities)
    for i in range(len(velocities)):
        lo = max(0, i - window // 2)
        hi = min(len(velocities), i + window // 2 + 1)
        window_vals = [v for v in velocities[lo:hi] if v is not None]
        if window_vals:
            smoothed[i] = sum(window_vals) / len(window_vals)

    return {
        "object_z_velocities": velocities,
        "object_z_velocity_smoothed": smoothed,
        "max_object_z_velocity_up": max_up,
        "max_object_z_velocity_down": max_down,
    }


def compute_slip_score(
    trace: list[dict[str, Any]],
    step: int,
) -> float:
    """Compute a kinematic slip score at a given step.

    Combines object-EEF distance drift, yaw drift, and vertical drop into a
    single scalar.  Higher values mean more severe slip.  The score is intended
    for relative comparison across episodes, not as an absolute threshold.
    """
    if not trace or step < 0 or step >= len(trace):
        return 0.0

    first = trace[0]
    r = trace[step]

    distance_first = _point_distance(first, "object", "eef")
    distance_now = _point_distance(r, "object", "eef")
    distance_drift = 0.0
    if distance_first is not None and distance_now is not None:
        distance_drift = abs(distance_now - distance_first)

    yaw_first_obj = _to_float(first.get("object_yaw"))
    yaw_now_obj = _to_float(r.get("object_yaw"))
    yaw_drift = 0.0
    if yaw_first_obj is not None and yaw_now_obj is not None:
        yaw_drift = abs(_angle_diff(yaw_now_obj, yaw_first_obj))

    z_first = _to_float(first.get("object_z"))
    z_now = _to_float(r.get("object_z"))
    z_drop = 0.0
    if z_first is not None and z_now is not None:
        z_drop = max(0.0, z_first - z_now)

    # Weights chosen so that each term contributes roughly equally for a severe
    # slip: 5 cm drift, 0.5 rad yaw, 5 cm drop.
    return float(
        10.0 * distance_drift
        + 1.0 * yaw_drift
        + 10.0 * z_drop
    )


def classify_seed24_slip(
    trace: list[dict[str, Any]],
    lift_threshold: float = 0.03,
    drop_threshold: float = 0.05,
    torsional_threshold: float = 0.3,
    env_success: bool | None = None,
) -> dict[str, Any]:
    """Classify the failure mode of a seed-24 style post-lift slip episode.

    Returns a coarse ``category`` plus supporting details.  The categories are
    intentionally aligned with the v1.8 forensic questions:

    - ``vertical_slip_after_lift``
    - ``torsional_slip_after_lift``
    - ``hold_instability``
    - ``grip_force_insufficient``
    - ``lift_acceleration_too_high``
    - ``orientation_realign_induced_slip``
    - ``metric_false_negative``
    - ``unknown``
    - ``success``

    If ``env_success`` is explicitly provided, it overrides trace-only
    heuristics.  This is important because the trace-only classifier can
    mis-label a successful but in-hand-reorienting episode as
    ``torsional_slip_after_lift``.
    """
    if not trace:
        return {"category": "unknown", "reason": "empty_trace"}

    drop_info = compute_lift_drop_forensics(trace, lift_threshold, drop_threshold)
    torsional = compute_torsional_slip_forensics(trace, torsional_threshold)
    gripper = compute_gripper_forensics(trace, drop_step=drop_info["drop_step"])
    velocity = compute_vertical_velocity_forensics(trace)

    if env_success is True:
        return {
            "category": "success",
            "reason": "env_success_rate_is_one",
            **drop_info,
            **torsional,
            **gripper,
            **velocity,
        }

    final_z = drop_info["final_object_z"]
    lifted = drop_info["lifted"]
    dropped = drop_info["object_dropped"]
    drop_step = drop_info["drop_step"]
    drop_phase = drop_info["drop_phase"]

    # Metric false negative: object clearly reached success height/yaw but the
    # coarse episode metric reports failure because it compares final height.
    last = trace[-1]
    object_yaw_error_final = _to_float(last.get("object_yaw_error"))
    success_height = final_z is not None and final_z > 0.15
    success_yaw = object_yaw_error_final is not None and object_yaw_error_final < 0.2
    if success_height and success_yaw:
        return {"category": "success", "reason": "final_state_meets_success_criteria"}

    if not lifted:
        return {"category": "unknown", "reason": "object_not_lifted", **drop_info, **torsional, **gripper}

    if not dropped:
        # Lifted but did not drop back below threshold.  Treat as orientation
        # alignment failure unless a torsional slip is present.
        if torsional["torsional_slip_detected"]:
            return {
                "category": "torsional_slip_after_lift",
                "reason": "lifted_without_catastrophic_drop_but_torsional_slip_detected",
                **drop_info,
                **torsional,
                **gripper,
                **velocity,
            }
        if object_yaw_error_final is not None and object_yaw_error_final > 0.2:
            return {
                "category": "orientation_realign_induced_slip",
                "reason": "lifted_but_yaw_alignment_failed",
                **drop_info,
                **torsional,
                **gripper,
                **velocity,
            }
        return {
            "category": "hold_instability",
            "reason": "lifted_but_neither_dropped_nor_aligned",
            **drop_info,
            **torsional,
            **gripper,
            **velocity,
        }

    # Object was lifted and then dropped.
    # If the gripper never blocked on the object, the root cause is insufficient
    # closing force / missed grasp, regardless of when the drop becomes visible.
    if not gripper["gripper_blocked"]:
        return {
            "category": "grip_force_insufficient",
            "reason": f"gripper_not_blocked_while_lifted_min={gripper.get('gripper_pos_min_while_lifted')}",
            **drop_info,
            **torsional,
            **gripper,
            **velocity,
        }

    # Check gripper release after it had blocked.
    if gripper["gripper_release_detected"]:
        return {
            "category": "grip_force_insufficient",
            "reason": "gripper_reopened_after_grasp",
            **drop_info,
            **torsional,
            **gripper,
            **velocity,
        }

    # Check for torsional slip that precedes or coincides with the drop.
    if torsional["torsional_slip_detected"]:
        if drop_phase in ("REORIENT", "STABILIZE", "ALIGN"):
            return {
                "category": "orientation_realign_induced_slip",
                "reason": f"torsional_slip_during_{drop_phase}",
                **drop_info,
                **torsional,
                **gripper,
                **velocity,
            }
        return {
            "category": "torsional_slip_after_lift",
            "reason": f"torsional_slip_during_{drop_phase}",
            **drop_info,
            **torsional,
            **gripper,
            **velocity,
        }

    # Drop during or immediately after LIFT with large upward/downward
    # acceleration suggests the lift motion itself destabilized the grasp.
    if drop_phase == "LIFT" or (drop_step is not None and drop_step < 50):
        max_down = velocity.get("max_object_z_velocity_down")
        if max_down is not None and max_down < -0.02:
            return {
                "category": "lift_acceleration_too_high",
                "reason": "rapid_vertical_drop_during_or_right_after_lift",
                **drop_info,
                **torsional,
                **gripper,
                **velocity,
            }

    # Drop in HOLD/ALIGN without torsional slip and without gripper release is
    # classified as hold instability / gradual contact relaxation.
    if drop_phase in ("HOLD", "ALIGN", "STABILIZE"):
        return {
            "category": "hold_instability",
            "reason": "gradual_drop_in_hold_or_align_without_torsional_slip",
            **drop_info,
            **torsional,
            **gripper,
            **velocity,
        }

    return {
        "category": "vertical_slip_after_lift",
        "reason": "lifted_then_dropped_without_clear_torsion_or_gripper_release",
        **drop_info,
        **torsional,
        **gripper,
        **velocity,
    }


def summarize_trace_for_forensics(
    trace: list[dict[str, Any]],
    env_success: bool | None = None,
) -> dict[str, Any]:
    """Return a concise summary dict for a single episode trace."""
    classification = classify_seed24_slip(trace, env_success=env_success)
    category = classification["category"]
    details = dict(classification)

    last = trace[-1] if trace else {}
    first = trace[0] if trace else {}

    # Phase trace summary.
    phase_trace: list[dict[str, Any]] = []
    current_phase: str | None = None
    phase_start = 0
    for i, r in enumerate(trace):
        phase = r.get("phase") or "UNKNOWN"
        if phase != current_phase:
            if current_phase is not None:
                phase_trace.append({
                    "phase": current_phase,
                    "start_step": phase_start,
                    "end_step": i - 1,
                })
            current_phase = phase
            phase_start = i
    if current_phase is not None:
        phase_trace.append({
            "phase": current_phase,
            "start_step": phase_start,
            "end_step": len(trace) - 1,
        })

    yaw_error_final = _to_float(last.get("object_yaw_error"))
    yaw_errors = [_to_float(r.get("object_yaw_error")) for r in trace if _to_float(r.get("object_yaw_error")) is not None]
    yaw_error_min = min(yaw_errors) if yaw_errors else None

    object_eef_dists = [_point_distance(r, "object", "eef") for r in trace]
    object_eef_dists_valid = [d for d in object_eef_dists if d is not None]

    action_norms = [_to_float(r.get("action_norm")) for r in trace if _to_float(r.get("action_norm")) is not None]

    return {
        "category": category,
        "phase_trace": phase_trace,
        "episode_steps": len(trace),
        "initial_object_y": first.get("object_y"),
        "initial_object_z": first.get("object_z"),
        "initial_object_yaw": first.get("object_yaw"),
        "target_yaw": last.get("target_yaw") or first.get("target_yaw"),
        "object_yaw_error_final": yaw_error_final,
        "object_yaw_error_min": yaw_error_min,
        "object_eef_distance_min": min(object_eef_dists_valid) if object_eef_dists_valid else None,
        "object_eef_distance_mean": (
            sum(object_eef_dists_valid) / len(object_eef_dists_valid) if object_eef_dists_valid else None
        ),
        "max_action_norm": max(action_norms) if action_norms else None,
        "mean_action_norm": (sum(action_norms) / len(action_norms) if action_norms else None),
        **details,
    }
