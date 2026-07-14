"""Promotion policy rules for Darwin v1.0."""

from __future__ import annotations

from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.evolution.evidence_level import (
    REAL_PROMOTION_STATUSES,
    SYNTHETIC_PROMOTION_STATUSES,
)

PROMOTION_LEVELS = [
    "local_asset_pose_alignment_fix_validated",
    "arena_gr1_gn1x_server_health_verified",
    "arena_official_baseline_scale_validated",
    "official_wrapper_configs_prepared",
    "official_reference_baseline_frozen",
    "official_wrapper_injection_smoke_passed",
    "official_candidate_rejected_adapter_wrapper_degraded",
    "official_adapter_wrapper_rollback_recovered",
    "official_environment_metric_guard_rejected",
    "official_environment_metric_guard_rollback_recovered",
    "action_wrappers_verified_on_policy_path",
    "official_action_wrapper_rejection_blocked_by_passive_drift",
    "official_action_wrapper_recovery_blocked",
    "rejected",
    "diagnosis_only",
    "blocked_external",
    "human_escalation",
    "experimental_only",
    "metric_positive_control_passed",
    "evaluation_mechanism_verified",
    "arena_toy_learned_policy_baseline_evaluated",
    "arena_real_learned_policy_baseline_evaluated",
    "darwin_wrapped_official_workflow_completed",
    "synthetic_evaluation_recipe_preferred",
    "candidate_recovery",
    "real_evaluation_recipe_preferred",
    "real_adapter_fix_recovery_pilot",
    "real_adapter_fix_recovery",
    "arena_real_adapter_fix_recovery_pilot",
    "arena_real_adapter_fix_recovery",
    "validated_recovery",
    "validated_transferable_skill",
]

# Real (L4+) statuses that synthetic statuses must never transition into.
_REAL_ONLY_STATUSES: set[str] = {
    "real_evaluation_recipe_preferred",
    "real_adapter_fix_recovery",
    "arena_real_adapter_fix_recovery",
    "validated_recovery",
    "validated_transferable_skill",
}

# Hard-blocked transitions: source -> set of destinations that are never allowed.
HARD_BLOCKED_TRANSITIONS: dict[str, set[str]] = {
    "blocked_external": set(PROMOTION_LEVELS) - {"blocked_external"},
    "diagnosis_only": {"candidate_recovery", "validated_recovery", "validated_transferable_skill"},
    "experimental_only": {"validated_recovery", "validated_transferable_skill"},
    "candidate_recovery": {"validated_transferable_skill"},
    # Metric-positive / evaluation-mechanism statuses are not recoveries and must
    # not be promoted to skill claims.
    "metric_positive_control_passed": {"candidate_recovery", "validated_recovery", "validated_transferable_skill"},
    "evaluation_mechanism_verified": {"candidate_recovery", "validated_recovery", "validated_transferable_skill"},
    "arena_toy_learned_policy_baseline_evaluated": {"candidate_recovery", "validated_recovery", "validated_transferable_skill"},
    # v1.4: synthetic recipe preference must not be upgraded to real claims.
    "synthetic_evaluation_recipe_preferred": set(_REAL_ONLY_STATUSES),
    # v1.4: real recipe/fix recoveries are not yet transferable skills.
    "real_evaluation_recipe_preferred": {"validated_transferable_skill"},
    "real_adapter_fix_recovery": {"validated_transferable_skill"},
    "arena_real_adapter_fix_recovery": {"validated_transferable_skill"},
}


def can_promote(source: str, destination: str) -> bool:
    """Check whether a transition between promotion levels is allowed."""
    if source == destination:
        return True
    if source not in PROMOTION_LEVELS or destination not in PROMOTION_LEVELS:
        return False
    blocked = HARD_BLOCKED_TRANSITIONS.get(source, set())
    return destination not in blocked


def evaluate_paired_no_regression(
    summary: PairedEvaluationSummary,
    min_rescued: int = 1,
    max_newly_failed: int = 0,
    min_candidate_rate: float = 0.0,
    max_new_failure_rate: float = 1.0,
) -> tuple[bool, list[str], list[str]]:
    """Evaluate a paired no-regression gate.

    Returns (passed, passed_gates, failed_gates).
    """
    passed: list[str] = []
    failed: list[str] = []

    if summary.rescued_count >= min_rescued:
        passed.append("rescued_count")
    else:
        failed.append(f"rescued_count={summary.rescued_count}<{min_rescued}")

    if summary.newly_failed_count <= max_newly_failed:
        passed.append("newly_failed_count")
    else:
        failed.append(f"newly_failed_count={summary.newly_failed_count}>{max_newly_failed}")

    if summary.candidate_success_rate >= min_candidate_rate:
        passed.append("candidate_success_rate")
    else:
        failed.append(f"candidate_success_rate={summary.candidate_success_rate}<{min_candidate_rate}")

    baseline_successes = summary.valid_pairs - int(
        summary.valid_pairs * summary.baseline_success_rate
    )
    denom = max(baseline_successes, 1)
    observed_new_failure_rate = summary.newly_failed_count / denom
    if observed_new_failure_rate <= max_new_failure_rate:
        passed.append("new_failure_rate")
    else:
        failed.append(
            f"new_failure_rate={observed_new_failure_rate:.3f}>{max_new_failure_rate}"
        )

    return len(failed) == 0, passed, failed


def promotion_level_from_summary(summary: PairedEvaluationSummary | None) -> str:
    """Infer the highest promotion level supported by paired evidence."""
    if summary is None:
        return "experimental_only"
    passed, _, _ = evaluate_paired_no_regression(summary)
    if passed and summary.rescued_count > 0:
        return "candidate_recovery"
    return "experimental_only"


def allowed_claims(status: str) -> list[str]:
    """Return claims allowed at a given promotion level."""
    mapping: dict[str, list[str]] = {
        "candidate_recovery": [
            "The recovery is a no-regression candidate on the evaluated seed/task set."
        ],
        "validated_recovery": [
            "The recovery is validated on the specific hold-out set."
        ],
        "validated_transferable_skill": [
            "The skill is transferable within the demonstrated scope."
        ],
        "experimental_only": [
            "The component is implemented, offline gates pass, and live control is safe."
        ],
        "metric_positive_control_passed": [
            "Darwin can detect metric-positive candidate behavior on real Arena traces."
        ],
        "evaluation_mechanism_verified": [
            "Darwin's paired evaluation / promotion engine can identify deterministic positive metric deltas."
        ],
        "arena_toy_learned_policy_baseline_evaluated": [
            "Darwin can train and evaluate a learned policy end-to-end on a synthetic Arena-like task through the standard adapter interface."
        ],
        "arena_real_learned_policy_baseline_evaluated": [
            "Darwin can run and evaluate a published real-environment Arena learned-policy baseline through the standard adapter interface."
        ],
        "darwin_wrapped_official_workflow_completed": [
            "Darwin can orchestrate the official Arena workflow end-to-end and produce audit artifacts."
        ],
        "blocked_external": [
            "Darwin can honestly block false promotion; the failure is routed to external escalation."
        ],
        "diagnosis_only": [
            "Darwin can diagnose this failure class."
        ],
        "human_escalation": [
            "The candidate is under human review."
        ],
        "rejected": [],
        # v1.4 real/synthetic recipe statuses.
        "real_adapter_fix_recovery": [
            "The adapter fix recovers baseline performance on the evaluated real-environment seed/task set."
        ],
        "arena_real_adapter_fix_recovery": [
            "The Arena adapter fix recovers baseline performance on the evaluated real-environment seed/task set."
        ],
        "real_evaluation_recipe_preferred": [
            "The real evaluation recipe is preferred on the evaluated real-environment seed/task set."
        ],
        "synthetic_evaluation_recipe_preferred": [
            "The evaluation recipe preference was demonstrated with synthetic/offline data only."
        ],
    }
    return mapping.get(status, [])


def disallowed_claims(status: str) -> list[str]:
    """Return claims disallowed at a given promotion level."""
    if status == "validated_transferable_skill":
        return ["universal robot capability", "official Arena leaderboard result"]
    if status == "validated_recovery":
        return ["transferable skill across objects/embodiments"]
    if status == "candidate_recovery":
        return [
            "transferable skill",
            "validated on independent task",
            "universal fix",
        ]
    if status in ("metric_positive_control_passed", "evaluation_mechanism_verified", "arena_toy_learned_policy_baseline_evaluated", "arena_real_learned_policy_baseline_evaluated", "darwin_wrapped_official_workflow_completed"):
        return [
            "transferable skill",
            "policy skill validated",
            "real-environment validation",
            "π0.5 improved",
            "official Arena leaderboard result",
            "official leaderboard result",
            "official_arena_leaderboard",
        ]
    if status == "experimental_only":
        return [
            "It improves success rate",
            "It is a promoted recovery",
        ]
    if status == "blocked_external":
        return ["Darwin solved it", "candidate recovery validated"]
    if status == "diagnosis_only":
        return ["Darwin can fix it", "Darwin has a validated recovery"]
    # v1.4 real/synthetic recipe statuses.
    if status in REAL_PROMOTION_STATUSES:
        return [
            "transferable skill",
            "validated on independent task",
            "universal fix",
            "official leaderboard result",
        ]
    if status in SYNTHETIC_PROMOTION_STATUSES:
        return [
            "real-environment validation",
            "transferable skill",
            "validated recovery",
            "official leaderboard result",
        ]
    return []
