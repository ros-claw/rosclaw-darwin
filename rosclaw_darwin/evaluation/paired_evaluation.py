"""Paired no-regression evaluation schema and utilities.

v1.10 replaces raw success-rate comparisons with per-seed paired evaluation:
for the same seed under the same perturbation protocol, a baseline policy and
a candidate policy are run and their outcomes are classified as
rescued / newly_failed / unchanged_success / unchanged_failure / invalid_pair.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from rosclaw_darwin.analysis.statistics import bootstrap_ci, mcnemar_test

DELTA_CLASS = Literal[
    "rescued",
    "newly_failed",
    "unchanged_success",
    "unchanged_failure",
    "invalid_pair",
]


def classify_pair(
    baseline_success: bool,
    candidate_success: bool,
    valid: bool = True,
) -> str:
    """Classify a single paired seed outcome.

    Parameters
    ----------
    baseline_success:
        Whether the baseline policy succeeded on this seed.
    candidate_success:
        Whether the candidate policy succeeded on this seed.
    valid:
        If False, the pair is marked ``invalid_pair`` regardless of outcomes.
    """
    if not valid:
        return "invalid_pair"
    if baseline_success and candidate_success:
        return "unchanged_success"
    if not baseline_success and not candidate_success:
        return "unchanged_failure"
    if not baseline_success and candidate_success:
        return "rescued"
    return "newly_failed"


class PairedSeedOutcome(BaseModel):
    """Outcome for a single seed under baseline-vs-candidate comparison."""

    seed: int
    baseline_success: bool
    candidate_success: bool

    baseline_failure_type: str | None = None
    candidate_failure_type: str | None = None

    baseline_artifact_dir: str
    candidate_artifact_dir: str

    delta_class: DELTA_CLASS = "unchanged_success"
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_delta_class(self) -> "PairedSeedOutcome":
        valid = "invalid_pair" not in self.notes
        self.delta_class = classify_pair(
            self.baseline_success, self.candidate_success, valid=valid
        )
        return self


class PairedEvaluationSummary(BaseModel):
    """Aggregate summary of a paired evaluation run."""

    task_id: str
    baseline_policy: str
    candidate_policy: str
    seed_range: str

    total_pairs: int = 0
    valid_pairs: int = 0

    rescued_count: int = 0
    newly_failed_count: int = 0
    unchanged_success_count: int = 0
    unchanged_failure_count: int = 0
    invalid_pair_count: int = 0

    net_delta: int = 0
    rescue_rate_on_baseline_failures: float = 0.0
    new_failure_rate_on_baseline_successes: float = 0.0

    baseline_success_rate: float = 0.0
    candidate_success_rate: float = 0.0

    mcnemar_p_value: float | None = None
    paired_bootstrap_ci: list[float] | None = None


class PairedEvaluationResult(BaseModel):
    """Full result object returned by a paired evaluation."""

    summary: PairedEvaluationSummary
    outcomes: list[PairedSeedOutcome]


def compute_paired_summary(
    outcomes: list[PairedSeedOutcome],
    task_id: str,
    baseline_policy: str,
    candidate_policy: str,
    seed_range: str,
) -> PairedEvaluationSummary:
    """Aggregate a list of per-seed paired outcomes into a summary."""
    total = len(outcomes)
    valid = [o for o in outcomes if o.delta_class != "invalid_pair"]
    valid_n = len(valid)

    rescued = [o for o in valid if o.delta_class == "rescued"]
    newly_failed = [o for o in valid if o.delta_class == "newly_failed"]
    unchanged_success = [o for o in valid if o.delta_class == "unchanged_success"]
    unchanged_failure = [o for o in valid if o.delta_class == "unchanged_failure"]
    invalid = [o for o in outcomes if o.delta_class == "invalid_pair"]

    baseline_successes = sum(1 for o in valid if o.baseline_success)
    candidate_successes = sum(1 for o in valid if o.candidate_success)

    baseline_failures = valid_n - baseline_successes
    rescue_rate = len(rescued) / baseline_failures if baseline_failures > 0 else 0.0
    new_failure_rate = (
        len(newly_failed) / baseline_successes if baseline_successes > 0 else 0.0
    )

    # Paired delta per seed: +1 rescued, -1 newly_failed, 0 otherwise.
    deltas = [int(o.candidate_success) - int(o.baseline_success) for o in valid]
    ci_lower, ci_upper = bootstrap_ci(deltas, n_boot=10000, alpha=0.05, seed=42)

    mcnemar = mcnemar_test(
        baseline_success_candidate_failure=len(newly_failed),
        baseline_failure_candidate_success=len(rescued),
        exact=True,
    )

    return PairedEvaluationSummary(
        task_id=task_id,
        baseline_policy=baseline_policy,
        candidate_policy=candidate_policy,
        seed_range=seed_range,
        total_pairs=total,
        valid_pairs=valid_n,
        rescued_count=len(rescued),
        newly_failed_count=len(newly_failed),
        unchanged_success_count=len(unchanged_success),
        unchanged_failure_count=len(unchanged_failure),
        invalid_pair_count=len(invalid),
        net_delta=len(rescued) - len(newly_failed),
        rescue_rate_on_baseline_failures=round(rescue_rate, 4),
        new_failure_rate_on_baseline_successes=round(new_failure_rate, 4),
        baseline_success_rate=round(baseline_successes / valid_n, 4) if valid_n else 0.0,
        candidate_success_rate=round(candidate_successes / valid_n, 4) if valid_n else 0.0,
        mcnemar_p_value=mcnemar["p_value"],
        paired_bootstrap_ci=[round(ci_lower, 4), round(ci_upper, 4)],
    )


__all__ = [
    "classify_pair",
    "PairedSeedOutcome",
    "PairedEvaluationSummary",
    "PairedEvaluationResult",
    "compute_paired_summary",
]
