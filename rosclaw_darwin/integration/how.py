"""HowBridge: extract skill candidates from experiences and failures."""

from __future__ import annotations

from typing import Any

from rosclaw_darwin.evolution.skill_registry import SkillCandidate
from rosclaw_darwin.tdl.fingerprints import primitive_fingerprint

# Map failure types to targeted skill templates.
FAILURE_SKILL_TEMPLATES: dict[str, dict[str, Any]] = {
    "grasp_failed": {
        "name": "grasp_adjust",
        "action_pattern": ["align_gripper", "close_gripper", "lift_slightly", "verify_hold"],
        "affordances": ["graspable"],
        "preconditions": ["near(object)", "gripper_free"],
        "postconditions": ["holding(object)"],
    },
    "handle_grasp_failed": {
        "name": "handle_grasp",
        "action_pattern": ["approach_handle", "align_gripper", "grasp_handle", "maintain_pose"],
        "affordances": ["graspable", "articulated"],
        "preconditions": ["near(handle)", "gripper_free"],
        "postconditions": ["holding(handle)"],
    },
    "object_dropped": {
        "name": "secure_hold",
        "action_pattern": ["detect_slip", "tighten_grip", "reorient_object", "verify_hold"],
        "affordances": ["graspable", "movable"],
        "preconditions": ["holding(object)"],
        "postconditions": ["object_stable"],
    },
    "collision": {
        "name": "collision_avoidance",
        "action_pattern": ["perceive_obstacles", "plan_safe_path", "execute_motion", "verify_clearance"],
        "affordances": ["navigable"],
        "preconditions": ["obstacle_nearby"],
        "postconditions": ["clear_path"],
    },
    "timeout": {
        "name": "efficient_execution",
        "action_pattern": ["prioritize_subgoal", "reduce_redundant_motion", "monitor_progress", "finish"],
        "affordances": [],
        "preconditions": ["time_constrained"],
        "postconditions": ["task_completed_within_budget"],
    },
    "door_not_opened": {
        "name": "open",
        "action_pattern": ["grasp(handle)", "pull_or_rotate", "verify_open"],
        "affordances": ["openable", "articulated"],
        "preconditions": ["near(handle)", "gripper_free"],
        "postconditions": ["is_open(object)"],
    },
    "object_not_found": {
        "name": "search",
        "action_pattern": ["scan_scene", "update_belief", "move_to_candidate", "verify_object"],
        "affordances": ["visible"],
        "preconditions": ["object_location_uncertain"],
        "postconditions": ["object_located"],
    },
    "navigation_failed": {
        "name": "navigate",
        "action_pattern": ["localize", "plan_path", "follow_path", "verify_pose"],
        "affordances": ["navigable"],
        "preconditions": ["start_pose_known", "goal_pose_known"],
        "postconditions": ["at(goal)"],
    },
    "planning_failed": {
        "name": "replan",
        "action_pattern": ["detect_plan_failure", "relax_constraint", "generate_plan", "execute_plan"],
        "affordances": [],
        "preconditions": ["plan_invalid"],
        "postconditions": ["valid_plan"],
    },
    "policy_crash": {
        "name": "safe_recovery",
        "action_pattern": ["detect_anomaly", "halt", "reset_safe_state", "resume"],
        "affordances": [],
        "preconditions": ["anomaly_detected"],
        "postconditions": ["system_stable"],
    },
    "robot_fallen": {
        "name": "balance_recovery",
        "action_pattern": ["detect_tilt", "stabilize_base", "recover_posture", "resume"],
        "affordances": [],
        "preconditions": ["unstable_pose"],
        "postconditions": ["stable_pose"],
    },
    "unknown": {
        "name": "adaptive_retry",
        "action_pattern": ["observe", "diagnose", "retry", "verify"],
        "affordances": [],
        "preconditions": ["failure_detected"],
        "postconditions": ["task_resumed"],
    },
}


class HowBridge:
    """Extract structured skill candidates from recorded experiences.

    The bridge looks at failure-type distributions across experiences and
    proposes targeted skills.  It also extracts a generic adaptive skill when
    success improved between attempts.
    """

    def __init__(self) -> None:
        pass

    def extract_skills(self, experiences: list[dict[str, Any]]) -> list[SkillCandidate]:
        """Extract skill candidates from experiences."""
        if not experiences:
            return []

        candidates: list[SkillCandidate] = []
        seen: set[str] = set()

        # Aggregate failure-type counts across experiences.
        failure_counts: dict[str, int] = {}
        success_rates: list[float] = []
        progress_means: list[float] = []
        task_ids: list[str] = []
        for exp in experiences:
            task_ids.append(exp.get("task_id", "unknown"))
            for ft, count in exp.get("failure_types", {}).items():
                failure_counts[ft] = failure_counts.get(ft, 0) + count
            metrics = exp.get("metrics", {})
            success_rates.append(metrics.get("success_rate", 0.0))
            progress_means.append(metrics.get("progress_mean", 0.0))

        success_gain = max(0.0, success_rates[-1] - success_rates[0]) if len(success_rates) > 1 else 0.0
        progress_gain = max(0.0, progress_means[-1] - progress_means[0]) if len(progress_means) > 1 else 0.0

        # Failure-driven skills.
        for failure_type, count in failure_counts.items():
            if count <= 0:
                continue
            template = FAILURE_SKILL_TEMPLATES.get(failure_type, FAILURE_SKILL_TEMPLATES["unknown"])
            fp = primitive_fingerprint(template["name"], sorted(template["affordances"]) + [failure_type])
            if fp in seen:
                continue
            seen.add(fp)
            candidate = SkillCandidate(
                id=f"skill_{template['name']}_{fp[:8]}",
                name=template["name"],
                action_pattern=template["action_pattern"],
                affordances=template["affordances"],
                preconditions=template.get("preconditions", []),
                postconditions=template.get("postconditions", []),
                source_task_ids=[],
                evidence={
                    "success_gain": success_gain,
                    "progress_gain": progress_gain,
                    "target_failure_type": failure_type,
                    "failure_count": count,
                },
                fingerprint=fp,
            )
            candidates.append(candidate)

        # Generic adaptive skill if success improved.
        if success_gain > 0.0:
            fp = "adaptive_skill"
            if fp not in seen:
                seen.add(fp)
                candidates.append(SkillCandidate(
                    id="skill_adaptive",
                    name="adaptive_skill",
                    action_pattern=["observe", "diagnose", "adapt", "execute"],
                    affordances=[],
                    source_task_ids=[],
                    evidence={
                        "success_gain": success_gain,
                        "progress_gain": progress_gain,
                    },
                    fingerprint=fp,
                ))

        return candidates
