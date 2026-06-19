"""Progress and failure-type metrics for lift_object-style tasks.

Pure-Python helpers that can run on the host (for tests and reports) and inside
the Arena Docker container (via import from run_eval.py) without pulling in
IsaacLab dependencies.
"""

from __future__ import annotations

import math
from typing import Any


def _dist(p1: dict[str, float | None], p2: dict[str, float | None]) -> float:
    """Euclidean distance with None safety."""
    if p1["x"] is None or p2["x"] is None:
        return float("inf")
    return math.sqrt(
        (p1["x"] - p2["x"]) ** 2
        + (p1["y"] - p2["y"]) ** 2
        + (p1["z"] - p2["z"]) ** 2
    )


def _point(step: dict[str, Any], prefix: str) -> dict[str, float | None]:
    return {
        "x": step.get(f"{prefix}_x"),
        "y": step.get(f"{prefix}_y"),
        "z": step.get(f"{prefix}_z"),
    }


def compute_lift_progress(
    eef_to_object_initial: float | None,
    eef_to_object_min: float | None,
    object_height_initial: float | None,
    object_height_max: float | None,
    object_to_target_initial: float | None,
    object_to_target_final: float | None,
    required_lift_height: float = 0.25,
) -> float:
    """Compute a scalar progress score in [0, 1]."""
    approach_progress = 0.0
    if eef_to_object_initial is not None and eef_to_object_min is not None:
        init = max(eef_to_object_initial, 1e-6)
        approach_progress = max(0.0, min(1.0, (init - eef_to_object_min) / init))

    lift_progress = 0.0
    if object_height_initial is not None and object_height_max is not None:
        lift_progress = max(
            0.0,
            min(1.0, (object_height_max - object_height_initial) / max(required_lift_height, 1e-6)),
        )

    target_progress = 0.0
    if object_to_target_initial is not None and object_to_target_final is not None:
        init = max(object_to_target_initial, 1e-6)
        target_progress = max(0.0, min(1.0, (init - object_to_target_final) / init))

    return 0.5 * approach_progress + 0.3 * lift_progress + 0.2 * target_progress


def _is_nan(value: Any) -> bool:
    try:
        return isinstance(value, float) and math.isnan(value)
    except TypeError:
        return False


def detect_metric_anomaly(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (is_anomaly, tags) for impossible metric values."""
    tags: list[str] = []
    height_delta = metrics.get("object_height_delta")
    if isinstance(height_delta, (int, float)) and abs(float(height_delta)) > 5.0:
        tags.append("object_height_delta_anomaly")
    obj_z = metrics.get("object_height_final") or metrics.get("object_height_max")
    if isinstance(obj_z, (int, float)):
        if float(obj_z) < -1.0 or float(obj_z) > 3.0:
            tags.append("object_z_anomaly")
    for key, value in metrics.items():
        if _is_nan(value):
            tags.append(f"nan:{key}")
    return bool(tags), tags


def classify_failure_class(
    episode_metrics: dict[str, Any],
    trace: list[dict[str, Any]] | None = None,
    workspace_y_threshold: float = 0.05,
    large_yaw_threshold: float = 1.2,
    orientation_threshold: float = 0.5,
) -> str:
    """Map a single episode to one of the v1.6 failure classes.

    The taxonomy is designed to separate workspace/reachability failures,
    grasp failures, in-hand slip, orientation failures, and data anomalies.
    """
    is_anomaly, anomaly_tags = detect_metric_anomaly(episode_metrics)
    if is_anomaly:
        if any("nan:" in tag for tag in anomaly_tags):
            return "metric_parser_error"
        return "physics_anomaly"

    success = bool(episode_metrics.get("success", False))
    if success:
        return "success"

    failure_type = episode_metrics.get("failure_type", "unknown_failure")
    phases_reached = set(episode_metrics.get("phases_reached", []))
    lifted = bool(episode_metrics.get("lift_phase_reached")) or (
        episode_metrics.get("object_height_delta", 0.0) > 0.03
    )
    reached = bool(
        episode_metrics.get("grasp_phase_reached")
        or episode_metrics.get("eef_to_object_distance_min", float("inf")) < 0.05
    )

    # Reachability / approach collision: never reached GRASP and object on +y edge.
    if not reached or "GRASP" not in phases_reached:
        initial_object_y: float | None = None
        if trace:
            initial_object_y = trace[0].get("object_y")
        if initial_object_y is None:
            initial_object_y = episode_metrics.get("object_y_initial")
        if isinstance(initial_object_y, (int, float)) and float(initial_object_y) > workspace_y_threshold:
            return "workspace_unreachable"
        if failure_type == "target_not_reached":
            return "approach_collision"
        return "approach_collision"

    # Grasp attempted but object not lifted.
    if "GRASP" in phases_reached and not lifted:
        return "grasp_failed" if failure_type == "object_not_lifted" else "object_not_lifted"

    # Lifted but dropped before success.
    if lifted and failure_type == "target_not_reached_after_lift":
        target_yaw: float | None = None
        object_yaw_error_final: float | None = None
        if trace:
            target_yaw = trace[-1].get("target_yaw")
            object_yaw_error_final = trace[-1].get("object_yaw_error")
        if target_yaw is None:
            target_yaw = episode_metrics.get("target_yaw")
        if object_yaw_error_final is None:
            object_yaw_error_final = episode_metrics.get("orientation_error_final")
        if isinstance(target_yaw, (int, float)) and abs(float(target_yaw)) >= large_yaw_threshold:
            if isinstance(object_yaw_error_final, (int, float)) and float(object_yaw_error_final) > orientation_threshold:
                return "large_yaw_slip"
        if isinstance(object_yaw_error_final, (int, float)) and float(object_yaw_error_final) > orientation_threshold:
            return "orientation_not_achieved"
        return "hold_instability"

    return "unknown"


def compute_failure_boundary_advancement(
    baseline_max_phase_scores: list[int],
    condition_max_phase_scores: list[int],
) -> dict[str, Any]:
    """Compute Failure Boundary Advancement (FBA) between two conditions."""
    phase_scores = {
        "APPROACH": 1,
        "DESCEND": 2,
        "GRASP": 3,
        "LIFT": 4,
        "ALIGN": 5,
        "HOLD": 6,
        "SUCCESS": 7,
    }

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    baseline_mean = _mean([float(s) for s in baseline_max_phase_scores])
    condition_mean = _mean([float(s) for s in condition_max_phase_scores])
    return {
        "baseline_mean_phase_score": round(baseline_mean, 4),
        "condition_mean_phase_score": round(condition_mean, 4),
        "fba": round(condition_mean - baseline_mean, 4),
        "phase_score_mapping": phase_scores,
    }


def infer_failure_type(
    reached_object: bool,
    lifted: bool,
    success: bool,
    nonzero_action_rate: float,
    lift_height_threshold: float = 0.01,
) -> str:
    """Map episode outcomes to a failure type string."""
    if nonzero_action_rate < 0.05:
        return "policy_noop"
    if not reached_object:
        return "target_not_reached"
    if reached_object and not lifted:
        return "object_not_lifted"
    if lifted and not success:
        return "target_not_reached_after_lift"
    if not success:
        return "timeout"
    return "unknown_failure"


def compute_episode_metrics(
    trace: list[dict[str, Any]],
    grasp_dist_threshold: float = 0.03,
    success_threshold: float = 0.06,
    lift_height_threshold: float = 0.03,
    required_lift_height: float = 0.25,
) -> dict[str, Any]:
    """Compute progress and failure-type metrics from a single episode trace."""
    if not trace:
        return {"failure_type": "unknown_failure", "episode_steps": 0}

    eef_dists = [_dist(_point(s, "eef"), _point(s, "object")) for s in trace]
    target_dists = [_dist(_point(s, "object"), _point(s, "target")) for s in trace]
    object_heights = [s.get("object_z") for s in trace if s.get("object_z") is not None]
    action_norms = [s.get("action_norm") for s in trace if s.get("action_norm") is not None]

    def _safe_first(values: list[float]) -> float | None:
        return values[0] if values else None

    def _safe_last(values: list[float]) -> float | None:
        return values[-1] if values else None

    def _safe_min(values: list[float]) -> float | None:
        finite = [v for v in values if v != float("inf")]
        return min(finite) if finite else None

    def _safe_max(values: list[float]) -> float | None:
        finite = [v for v in values if v != float("inf")]
        return max(finite) if finite else None

    eef_initial = _safe_first(eef_dists)
    eef_final = _safe_last(eef_dists)
    eef_min = _safe_min(eef_dists)

    target_initial = _safe_first(target_dists)
    target_final = _safe_last(target_dists)
    target_min = _safe_min(target_dists)

    object_initial = object_heights[0] if object_heights else None
    object_final = object_heights[-1] if object_heights else None
    object_max = max(object_heights) if object_heights else None
    object_delta = (
        (object_final - object_initial)
        if object_initial is not None and object_final is not None
        else 0.0
    )

    # An object that has been lifted by more than the threshold is implicitly
    # considered "reached" even if the end-effector distance estimate is noisy
    # (e.g. when using gripper geometry instead of the flange centre).
    reached_object = (
        (eef_min is not None and eef_min < grasp_dist_threshold)
        or object_delta > lift_height_threshold
    )
    lifted = object_delta > lift_height_threshold
    # Use the minimum object-to-target distance during the episode to align
    # with Arena's early-success termination (the final state may overshoot).
    success = bool(
        reached_object
        and lifted
        and target_min is not None
        and target_min < success_threshold
    )

    nonzero_actions = sum(1 for n in action_norms if n is not None and n > 1e-4)
    nonzero_rate = nonzero_actions / max(1, len(action_norms))

    failure_type = infer_failure_type(
        reached_object=reached_object,
        lifted=lifted,
        success=success,
        nonzero_action_rate=nonzero_rate,
        lift_height_threshold=lift_height_threshold,
    )

    progress = compute_lift_progress(
        eef_to_object_initial=eef_initial,
        eef_to_object_min=eef_min,
        object_height_initial=object_initial,
        object_height_max=object_max,
        object_to_target_initial=target_initial,
        object_to_target_final=target_final,
        required_lift_height=required_lift_height,
    )

    # Build a concise phase trace from step-level phase annotations.
    phase_trace: list[dict[str, Any]] = []
    current_phase: str | None = None
    phase_start: int = 0
    phases_reached: set[str] = set()
    for i, step in enumerate(trace):
        phase = step.get("phase") or "UNKNOWN"
        phases_reached.add(phase)
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

    return {
        "success": success,
        "failure_type": failure_type,
        "progress": round(progress, 4),
        "eef_to_object_distance_initial": eef_initial,
        "eef_to_object_distance_min": eef_min,
        "eef_to_object_distance_final": eef_final,
        "eef_to_object_distance_delta": (
            (eef_initial - eef_final)
            if eef_initial is not None and eef_final is not None
            else None
        ),
        "object_to_target_distance_initial": target_initial,
        "object_to_target_distance_min": target_min,
        "object_to_target_distance_final": target_final,
        "object_to_target_distance_delta": (
            (target_initial - target_final)
            if target_initial is not None and target_final is not None
            else None
        ),
        "object_height_initial": object_initial,
        "object_height_final": object_final,
        "object_height_max": object_max,
        "object_height_delta": object_delta,
        "mean_action_norm": (
            float(sum(action_norms) / len(action_norms)) if action_norms else None
        ),
        "max_action_norm": max(action_norms) if action_norms else None,
        "nonzero_action_rate": nonzero_rate,
        "episode_steps": len(trace),
        "phase_trace": phase_trace,
        "phases_reached": sorted(phases_reached),
        "approach_phase_reached": "APPROACH" in phases_reached,
        "grasp_phase_reached": "GRASP" in phases_reached,
        "lift_phase_reached": "LIFT" in phases_reached,
        "target_reached": success,
    }


def summarize_episodes(
    episode_metrics: list[dict[str, Any]],
    is_oracle: bool = False,
) -> dict[str, Any]:
    """Aggregate per-episode metrics into a summary dict."""
    if not episode_metrics:
        return {"episode_metrics": []}

    successes = [e["success"] for e in episode_metrics]
    progress_values = [e["progress"] for e in episode_metrics]

    failure_counts: dict[str, int] = {}
    for ep in episode_metrics:
        if not ep["success"]:
            failure_counts[ep["failure_type"]] = failure_counts.get(ep["failure_type"], 0) + 1

    def _mean(values: list[Any]) -> float | None:
        numeric = [v for v in values if isinstance(v, (int, float))]
        return round(sum(numeric) / len(numeric), 4) if numeric else None

    summary: dict[str, Any] = {
        "success_rate": round(sum(successes) / len(successes), 4),
        "progress_mean": round(sum(progress_values) / len(progress_values), 4),
        "progress_min": round(min(progress_values), 4),
        "progress_max": round(max(progress_values), 4),
        "eef_to_object_distance_initial_mean": _mean(
            [e["eef_to_object_distance_initial"] for e in episode_metrics]
        ),
        "eef_to_object_distance_min_mean": _mean(
            [e["eef_to_object_distance_min"] for e in episode_metrics]
        ),
        "eef_to_object_distance_final_mean": _mean(
            [e["eef_to_object_distance_final"] for e in episode_metrics]
        ),
        "object_height_delta_mean": _mean([e["object_height_delta"] for e in episode_metrics]),
        "object_height_max_mean": _mean([e["object_height_max"] for e in episode_metrics]),
        "num_episodes": len(episode_metrics),
        "num_success": int(sum(successes)),
        "failure_counts": failure_counts,
        "episode_metrics": episode_metrics,
    }

    if is_oracle:
        summary["skill_discovery_rate"] = None
        summary["evolution_score"] = None
        summary["skill_candidate_count"] = 0
        summary["validated_skill_count"] = 0
        summary["leaderboard_excluded"] = True
        summary["can_claim_capability"] = False

    return summary
