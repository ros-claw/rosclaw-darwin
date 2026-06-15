"""Grasp stability metrics for goal_pose diagnosis.

These metrics replace the naive ``gripper_pos < threshold`` grasp-success proxy
with object-centric measures: whether the object was lifted, whether it
followed the end-effector, how long it was held, and whether it dropped.
"""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point(step: dict[str, Any], prefix: str) -> tuple[float | None, float | None, float | None]:
    return (
        _to_float(step.get(f"{prefix}_x")),
        _to_float(step.get(f"{prefix}_y")),
        _to_float(step.get(f"{prefix}_z")),
    )


def _dist(p1: tuple[float | None, ...], p2: tuple[float | None, ...]) -> float | None:
    if None in p1 or None in p2 or len(p1) != len(p2):
        return None
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def infer_grasp_stability(
    trace: list[dict[str, Any]],
    lift_threshold: float = 0.10,
    drop_threshold: float = 0.05,
    follow_threshold: float = 0.10,
) -> dict[str, Any]:
    """Compute object-following grasp stability metrics from a step trace.

    Args:
        trace: list of step records produced by a policy.
        lift_threshold: object height delta considered a lift.
        drop_threshold: height fall from peak considered a drop.
        follow_threshold: maximum object-eef distance variance considered
            stable following.

    Returns:
        dict with object_lifted, object_follows_eef, held_duration_steps,
        drop_detected, drop_step, height stats, and a composite
        grasp_stability_score in [0, 1].
    """
    if not trace:
        return {
            "object_lifted": False,
            "object_follows_eef": False,
            "held_duration_steps": 0,
            "drop_detected": False,
            "drop_step": None,
            "object_height_peak": None,
            "object_height_final": None,
            "object_height_drop_after_peak": None,
            "relative_object_eef_distance_mean": None,
            "relative_object_eef_distance_max": None,
            "grasp_stability_score": 0.0,
        }

    heights = [_to_float(s.get("object_z")) for s in trace]
    valid_heights = [h for h in heights if h is not None]

    object_initial = valid_heights[0] if valid_heights else None
    object_final = valid_heights[-1] if valid_heights else None
    object_peak = max(valid_heights) if valid_heights else None
    object_height_drop_after_peak = (
        (object_peak - object_final) if object_peak is not None and object_final is not None else None
    )

    object_lifted = False
    if object_initial is not None and object_peak is not None:
        object_lifted = (object_peak - object_initial) >= lift_threshold

    drop_detected = False
    drop_step: int | None = None
    if object_lifted and object_peak is not None and object_final is not None:
        if object_final < object_peak - drop_threshold:
            drop_detected = True
            # Find the first step after the peak where the drop crosses threshold.
            peak_idx = next((i for i, h in enumerate(valid_heights) if h == object_peak), 0)
            for i in range(peak_idx, len(valid_heights)):
                if valid_heights[i] < object_peak - drop_threshold:
                    drop_step = i
                    break

    # Object-eef distance during lift and hold (ignore approach).
    distances: list[float] = []
    lift_started = False
    for i, step in enumerate(trace):
        obj_z = _to_float(step.get("object_z"))
        if obj_z is not None and object_initial is not None and not lift_started:
            if obj_z - object_initial >= lift_threshold * 0.5:
                lift_started = True
        if not lift_started:
            continue
        d = _dist(_point(step, "object"), _point(step, "eef"))
        if d is not None:
            distances.append(d)

    mean_dist = sum(distances) / len(distances) if distances else None
    max_dist = max(distances) if distances else None
    object_follows_eef = False
    if mean_dist is not None and max_dist is not None:
        object_follows_eef = mean_dist < follow_threshold and max_dist < follow_threshold * 2

    # Held duration: consecutive steps after lift start where object stays up.
    held_duration_steps = 0
    if lift_started and valid_heights:
        for h in valid_heights:
            if h - (object_initial or 0.0) >= lift_threshold * 0.5:
                held_duration_steps += 1
            elif held_duration_steps > 0:
                break

    # Composite score: lifted + not dropped + follows eef.
    score = 0.0
    if object_lifted:
        score += 0.4
    if object_lifted and not drop_detected:
        score += 0.35
    if object_follows_eef:
        score += 0.25

    return {
        "object_lifted": object_lifted,
        "object_follows_eef": object_follows_eef,
        "held_duration_steps": held_duration_steps,
        "drop_detected": drop_detected,
        "drop_step": drop_step,
        "object_height_peak": object_peak,
        "object_height_final": object_final,
        "object_height_drop_after_peak": object_height_drop_after_peak,
        "relative_object_eef_distance_mean": mean_dist,
        "relative_object_eef_distance_max": max_dist,
        "grasp_stability_score": round(score, 4),
    }


def summarize_grasp_stability(
    traces: list[list[dict[str, Any]]],
    lift_threshold: float = 0.10,
    drop_threshold: float = 0.05,
    follow_threshold: float = 0.10,
) -> dict[str, Any]:
    """Aggregate grasp stability metrics across episodes."""
    per_episode = [
        infer_grasp_stability(t, lift_threshold, drop_threshold, follow_threshold)
        for t in traces
    ]
    if not per_episode:
        return {"per_episode": [], "summary": {}}

    lifted = sum(1 for p in per_episode if p["object_lifted"])
    follows = sum(1 for p in per_episode if p["object_follows_eef"])
    dropped = sum(1 for p in per_episode if p["drop_detected"])
    scores = [p["grasp_stability_score"] for p in per_episode]

    summary = {
        "num_episodes": len(per_episode),
        "object_lifted_count": lifted,
        "object_lifted_rate": round(lifted / len(per_episode), 4),
        "object_follows_eef_count": follows,
        "object_follows_eef_rate": round(follows / len(per_episode), 4),
        "drop_detected_count": dropped,
        "drop_detected_rate": round(dropped / len(per_episode), 4),
        "grasp_stability_score_mean": round(sum(scores) / len(scores), 4),
        "grasp_stability_score_min": round(min(scores), 4),
        "grasp_stability_score_max": round(max(scores), 4),
    }
    return {"per_episode": per_episode, "summary": summary}
