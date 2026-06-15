"""FailureSignature v2: fine-grained failure characterization.

FailureSignature moves beyond coarse failure_type to explain *why* an episode
failed.  It is derived from per-episode metrics, phase traces, and optionally a
step-level trace.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rosclaw_darwin.evaluation.grasp_metrics import infer_grasp_stability
from rosclaw_darwin.tdl.schema import Task


class FailureSignature(BaseModel):
    task_id: str
    episode_id: int

    failure_type: str
    success: bool = False
    dominant_bottleneck: str | None = None
    phase_at_failure: str | None = None

    # approach / reach
    eef_to_object_distance_min: float | None = None
    eef_to_object_distance_final: float | None = None
    reached_object: bool = False

    # grasp
    grasp_phase_reached: bool = False
    close_gripper_completed: bool = False
    grasp_verified: bool | None = None
    gripper_closed_ratio: float | None = None

    # lift
    object_lifted: bool = False
    object_height_delta: float | None = None
    object_height_max: float | None = None
    lift_phase_reached: bool = False

    # drop / slip
    object_dropped: bool = False
    drop_step: int | None = None
    slip_score: float | None = None
    held_duration_steps: int | None = None
    object_follows_eef: bool | None = None
    rotation_induced_slip: bool = False
    hold_instability: bool = False

    # target alignment
    target_residual_final: float | None = None
    target_residual_min: float | None = None
    target_alignment_gap: float | None = None
    hold_at_target_steps: int | None = None

    # orientation / pose
    orientation_error_final: float | None = None
    orientation_error_min: float | None = None
    orientation_requirement_present: bool = False
    eef_yaw_final: float | None = None
    object_yaw_final: float | None = None
    yaw_transferred_to_object: bool = False
    yaw_not_transferred_to_object: bool = False

    # gripper closure diagnostic
    blocked_gripper_normal: bool | None = None
    blocked_gripper_abnormal: bool | None = None
    gripper_pos_min: float | None = None

    # action / controller
    nonzero_action_rate: float | None = None
    mean_action_norm: float | None = None
    controller_response_low: bool = False

    # interpretation
    signature_tags: list[str] = Field(default_factory=list)
    hint_relevant_tags: list[str] = Field(default_factory=list)


# Default thresholds; callers can override via thresholds dict.
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "reach_threshold": 0.05,
    "grasp_height_delta": 0.03,
    "lift_threshold": 0.10,
    "drop_threshold": 0.05,
    "target_success_threshold": 0.03,
    "orientation_threshold": 0.15,
    "action_norm_low": 0.01,
    "high_progress_threshold": 0.90,
}


def _has_orientation_requirement(task: Task) -> bool:
    """Guess whether the task cares about orientation."""
    primitives = [p.name.lower() for p in task.primitives]
    if any("orient" in p or "rotate" in p or "pose" in p for p in primitives):
        return True
    if "goal_pose" in task.id.lower():
        return True
    return False


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def infer_failure_signature(
    task: Task,
    episode_metrics: dict[str, Any],
    phase_trace: list[str] | None = None,
    trace: list[dict[str, Any]] | None = None,
    thresholds: dict[str, float] | None = None,
) -> FailureSignature:
    """Infer a rich FailureSignature from a single episode's data."""
    thr = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}

    episode_id = int(episode_metrics.get("episode_id", 0))
    failure_type = str(episode_metrics.get("failure_type") or "unknown")
    success = bool(episode_metrics.get("success", False))
    progress = _to_float(episode_metrics.get("progress"), 0.0)

    # Distance / reach.
    eef_min = _to_float(episode_metrics.get("eef_to_object_distance_min"))
    eef_final = _to_float(episode_metrics.get("eef_to_object_distance_final"))
    reached = eef_min is not None and eef_min <= thr["reach_threshold"]

    # Gripper / grasp.
    gripper_min = _to_float(episode_metrics.get("gripper_pos_min"))
    gripper_final = _to_float(episode_metrics.get("gripper_pos_final"))
    close_completed = gripper_min is not None and gripper_min <= 0.02

    # Height / lift.
    height_initial = _to_float(episode_metrics.get("object_height_initial"))
    height_max = _to_float(episode_metrics.get("object_height_max"))
    height_final = _to_float(episode_metrics.get("object_height_final"))
    height_delta = _to_float(episode_metrics.get("object_height_delta"))
    if height_delta is None and height_initial is not None and height_max is not None:
        height_delta = height_max - height_initial
    object_lifted = height_delta is not None and height_delta >= thr["lift_threshold"]

    # Drop detection.
    object_dropped = False
    drop_step: int | None = None
    if object_lifted and height_max is not None and height_final is not None:
        if height_final < height_max - thr["drop_threshold"]:
            object_dropped = True
            drop_step = int(episode_metrics.get("max_height_step", episode_metrics.get("final_step", 0)))

    # Target residual.
    target_residual_final = _to_float(episode_metrics.get("object_to_target_distance_final"))
    target_residual_min = _to_float(episode_metrics.get("object_to_target_distance_min"))
    target_gap = target_residual_final

    # Orientation.
    orientation_final = _to_float(episode_metrics.get("orientation_error_final"))
    orientation_min = _to_float(episode_metrics.get("orientation_error_min"))
    orientation_required = _has_orientation_requirement(task)

    # Action stats from step-level trace.
    nonzero_action_rate: float | None = None
    mean_action_norm: float | None = None
    if trace:
        norms = [_to_float(step.get("action_norm")) for step in trace if "action_norm" in step]
        valid_norms = [n for n in norms if n is not None]
        if valid_norms:
            mean_action_norm = sum(valid_norms) / len(valid_norms)
            nonzero_action_rate = sum(1 for n in valid_norms if n > thr["action_norm_low"]) / len(valid_norms)

    # Grasp stability from step-level trace (v3).
    grasp_stability = infer_grasp_stability(trace, lift_threshold=thr["lift_threshold"], drop_threshold=thr["drop_threshold"]) if trace else None
    object_follows_eef = grasp_stability["object_follows_eef"] if grasp_stability else None
    rotation_induced_slip = False
    hold_instability = False
    yaw_transferred_to_object = False
    yaw_not_transferred_to_object = False
    eef_yaw_final = None
    object_yaw_final = None
    gripper_pos_min = None
    if trace:
        gripper_positions = [s.get("gripper_pos") for s in trace if s.get("gripper_pos") is not None]
        if gripper_positions:
            gripper_pos_min = min(gripper_positions)
        last = trace[-1]
        eef_yaw_final = _to_float(last.get("eef_yaw"))
        object_yaw_final = _to_float(last.get("object_yaw"))
        if grasp_stability and grasp_stability["drop_detected"]:
            drop_step_trace = grasp_stability.get("drop_step")
            if drop_step_trace is not None:
                # Map step index in lifted trace back to global step if possible.
                drop_step = drop_step_trace
                drop_phase = None
                for i, s in enumerate(trace):
                    if i == drop_step:
                        drop_phase = s.get("phase")
                        break
                if drop_phase in ("REORIENT",):
                    rotation_induced_slip = True
                elif drop_phase in ("HOLD",):
                    hold_instability = True
        if orientation_required and eef_yaw_final is not None and object_yaw_final is not None:
            # Detect whether object yaw changed while eef yaw did not.
            object_yaw_initial = _to_float(trace[0].get("object_yaw"))
            eef_yaw_initial = _to_float(trace[0].get("eef_yaw"))
            if object_yaw_initial is not None and abs(object_yaw_final - object_yaw_initial) > 0.05:
                if eef_yaw_initial is not None and abs(eef_yaw_final - eef_yaw_initial) < 0.05:
                    yaw_not_transferred_to_object = True
                else:
                    yaw_transferred_to_object = True

    # Blocked gripper diagnostic: 0.024 is considered normal for held cube.
    blocked_gripper_normal = None
    blocked_gripper_abnormal = None
    if gripper_pos_min is not None:
        blocked_gripper_normal = 0.015 <= gripper_pos_min <= 0.035
        blocked_gripper_abnormal = gripper_pos_min > 0.04 or gripper_pos_min < 0.001

    # Phase at failure.
    phase_at_failure = None
    if phase_trace:
        phase_at_failure = phase_trace[-1]

    # Build tags.
    tags: list[str] = []
    if progress >= thr["high_progress_threshold"] and not success:
        tags.append("high_progress_zero_success")

    if not reached:
        tags.append("not_reached")
    else:
        if not object_lifted and not close_completed:
            tags.append("reached_but_not_grasped")
        elif not object_lifted and close_completed:
            tags.append("grasped_but_not_lifted")

    if object_lifted:
        if target_gap is not None and target_gap > thr["target_success_threshold"]:
            tags.append("lifted_but_not_aligned")
            tags.append("final_alignment_gap")
        if object_dropped:
            tags.append("lifted_then_dropped")
            tags.append("unstable_grasp")
            if rotation_induced_slip:
                tags.append("rotation_induced_slip")
            if hold_instability:
                tags.append("hold_instability")
        if object_follows_eef:
            tags.append("object_follows_eef")
        elif object_follows_eef is False:
            tags.append("object_not_following_eef")
        if yaw_not_transferred_to_object:
            tags.append("yaw_not_transferred_to_object")
        if yaw_transferred_to_object:
            tags.append("yaw_transferred_but_slipped")
        if blocked_gripper_normal:
            tags.append("blocked_gripper_normal")
        if blocked_gripper_abnormal:
            tags.append("blocked_gripper_abnormal")

    if orientation_required and orientation_final is not None and orientation_final > thr["orientation_threshold"]:
        tags.append("orientation_gap")

    if nonzero_action_rate is not None and nonzero_action_rate < 0.1:
        tags.append("policy_noop")

    if mean_action_norm is not None and mean_action_norm <= thr["action_norm_low"]:
        tags.append("controller_slow")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_tags: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    # Dominant bottleneck.
    dominant_bottleneck = _choose_dominant_bottleneck(unique_tags, failure_type)

    # Hint-relevant tags are the same as signature tags for now; callers can refine.
    hint_relevant_tags = list(unique_tags)

    return FailureSignature(
        task_id=task.id,
        episode_id=episode_id,
        failure_type=failure_type,
        success=success,
        dominant_bottleneck=dominant_bottleneck,
        phase_at_failure=phase_at_failure,
        eef_to_object_distance_min=eef_min,
        eef_to_object_distance_final=eef_final,
        reached_object=reached,
        grasp_phase_reached="GRASP" in (phase_trace or []),
        close_gripper_completed=close_completed,
        gripper_closed_ratio=gripper_final,
        object_lifted=object_lifted,
        object_height_delta=height_delta,
        object_height_max=height_max,
        lift_phase_reached="LIFT" in (phase_trace or []),
        object_dropped=object_dropped,
        drop_step=drop_step,
        held_duration_steps=_to_int(episode_metrics.get("held_duration_steps")),
        object_follows_eef=object_follows_eef,
        rotation_induced_slip=rotation_induced_slip,
        hold_instability=hold_instability,
        target_residual_final=target_residual_final,
        target_residual_min=target_residual_min,
        target_alignment_gap=target_gap,
        hold_at_target_steps=_to_int(episode_metrics.get("hold_at_target_steps")),
        orientation_error_final=orientation_final,
        orientation_error_min=orientation_min,
        orientation_requirement_present=orientation_required,
        eef_yaw_final=eef_yaw_final,
        object_yaw_final=object_yaw_final,
        yaw_transferred_to_object=yaw_transferred_to_object,
        yaw_not_transferred_to_object=yaw_not_transferred_to_object,
        blocked_gripper_normal=blocked_gripper_normal,
        blocked_gripper_abnormal=blocked_gripper_abnormal,
        gripper_pos_min=gripper_pos_min,
        nonzero_action_rate=nonzero_action_rate,
        mean_action_norm=mean_action_norm,
        controller_response_low=bool(mean_action_norm is not None and mean_action_norm <= thr["action_norm_low"]),
        signature_tags=unique_tags,
        hint_relevant_tags=hint_relevant_tags,
    )


def _choose_dominant_bottleneck(tags: list[str], failure_type: str) -> str | None:
    """Pick the most actionable bottleneck from tags."""
    priority = [
        "yaw_not_transferred_to_object",
        "rotation_induced_slip",
        "hold_instability",
        "lifted_then_dropped",
        "unstable_grasp",
        "object_not_following_eef",
        "grasped_but_not_lifted",
        "reached_but_not_grasped",
        "final_alignment_gap",
        "orientation_gap",
        "not_reached",
        "policy_noop",
        "controller_slow",
    ]
    for candidate in priority:
        if candidate in tags:
            return candidate
    # Fallback to failure_type-derived bottleneck.
    mapping = {
        "target_not_reached_after_lift": "final_alignment_gap",
        "object_not_lifted": "grasp_stability",
        "grasp_failed": "grasp_stability",
        "target_not_reached": "approach",
        "timeout": "policy_noop",
    }
    return mapping.get(failure_type)


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def infer_failure_signatures_for_run(
    task: Task,
    episode_metrics: list[dict[str, Any]],
    phase_traces: list[dict[str, Any]] | None = None,
    traces: list[list[dict[str, Any]]] | None = None,
    thresholds: dict[str, float] | None = None,
) -> list[FailureSignature]:
    """Infer FailureSignature objects for every episode in a run."""
    phase_traces = phase_traces or []
    traces = traces or []
    signatures: list[FailureSignature] = []
    for i, ep in enumerate(episode_metrics):
        phase_trace: list[str] | None = None
        if i < len(phase_traces):
            pt = phase_traces[i]
            if isinstance(pt, dict):
                phase_trace = pt.get("phases") or pt.get("phase_trace") or []
            elif isinstance(pt, list):
                phase_trace = pt
        trace = traces[i] if i < len(traces) else None
        signatures.append(
            infer_failure_signature(
                task=task,
                episode_metrics=ep,
                phase_trace=phase_trace,
                trace=trace,
                thresholds=thresholds,
            )
        )
    return signatures
