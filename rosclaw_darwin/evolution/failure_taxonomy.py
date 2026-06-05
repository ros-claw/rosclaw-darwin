"""Failure taxonomy for embodied agent evaluation."""

from __future__ import annotations

from enum import Enum


class FailureType(str, Enum):
    timeout = "timeout"
    collision = "collision"
    object_dropped = "object_dropped"
    grasp_failed = "grasp_failed"
    handle_grasp_failed = "handle_grasp_failed"
    door_not_opened = "door_not_opened"
    object_not_found = "object_not_found"
    navigation_failed = "navigation_failed"
    planning_failed = "planning_failed"
    policy_crash = "policy_crash"
    robot_fallen = "robot_fallen"
    unknown = "unknown"


def infer_failure_type(metrics: dict, logs: str | None = None) -> FailureType:
    """Infer failure type from metrics and optional logs."""
    if logs and "grasp" in logs.lower() and "handle" in logs.lower():
        return FailureType.handle_grasp_failed
    if logs and "navigation" in logs.lower():
        return FailureType.navigation_failed
    if logs and "collision" in logs.lower():
        return FailureType.collision
    if logs and "dropped" in logs.lower():
        return FailureType.object_dropped
    if logs and "planning" in logs.lower():
        return FailureType.planning_failed
    if logs and "crash" in logs.lower():
        return FailureType.policy_crash
    if logs and "fallen" in logs.lower():
        return FailureType.robot_fallen

    # Heuristic from metrics
    if metrics.get("step_count", 0) >= metrics.get("max_steps", 0) - 1:
        return FailureType.timeout
    if metrics.get("collision_count", 0) > 3:
        return FailureType.collision

    return FailureType.unknown
