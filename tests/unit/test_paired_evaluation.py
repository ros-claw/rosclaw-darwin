"""Unit tests for paired evaluation schema and summary computation."""

from __future__ import annotations

import math

import pytest

from rosclaw_darwin.evaluation.paired_evaluation import (
    PairedEvaluationResult,
    PairedEvaluationSummary,
    PairedSeedOutcome,
    classify_pair,
    compute_paired_summary,
)


def test_classify_pair_all_cases():
    assert classify_pair(True, True) == "unchanged_success"
    assert classify_pair(False, False) == "unchanged_failure"
    assert classify_pair(False, True) == "rescued"
    assert classify_pair(True, False) == "newly_failed"
    assert classify_pair(True, False, valid=False) == "invalid_pair"


def test_paired_seed_outcome_delta_class_derived():
    outcome = PairedSeedOutcome(
        seed=0,
        baseline_success=True,
        candidate_success=False,
        baseline_artifact_dir="/tmp/baseline",
        candidate_artifact_dir="/tmp/candidate",
    )
    assert outcome.delta_class == "newly_failed"


def test_paired_seed_outcome_invalid_note():
    outcome = PairedSeedOutcome(
        seed=1,
        baseline_success=False,
        candidate_success=True,
        baseline_artifact_dir="/tmp/baseline",
        candidate_artifact_dir="/tmp/candidate",
        notes=["asset_fallback_used", "invalid_pair"],
    )
    assert outcome.delta_class == "invalid_pair"


def test_compute_paired_summary_known_table():
    """Use a 2x2 table with b=1, c=9.

    Baseline failures: 10, baseline successes: 10 (total 20).
    Candidate successes: baseline successes (10 - 1) + rescued (9) = 18.
    """
    outcomes = []
    for seed in range(10):
        outcomes.append(
            PairedSeedOutcome(
                seed=seed,
                baseline_success=False,
                candidate_success=seed < 9,
                baseline_artifact_dir="/tmp/b",
                candidate_artifact_dir="/tmp/c",
            )
        )
    for seed in range(10, 20):
        outcomes.append(
            PairedSeedOutcome(
                seed=seed,
                baseline_success=True,
                candidate_success=seed >= 11,
                baseline_artifact_dir="/tmp/b",
                candidate_artifact_dir="/tmp/c",
            )
        )

    summary = compute_paired_summary(
        outcomes,
        task_id="test_task",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:20",
    )
    assert isinstance(summary, PairedEvaluationSummary)
    assert summary.total_pairs == 20
    assert summary.valid_pairs == 20
    assert summary.rescued_count == 9
    assert summary.newly_failed_count == 1
    assert summary.unchanged_success_count == 9
    assert summary.unchanged_failure_count == 1
    assert summary.net_delta == 8
    assert summary.baseline_success_rate == 0.5
    assert summary.candidate_success_rate == 0.9
    assert summary.rescue_rate_on_baseline_failures == 0.9
    assert summary.new_failure_rate_on_baseline_successes == 0.1
    assert summary.mcnemar_p_value is not None
    assert summary.mcnemar_p_value < 0.05
    assert summary.paired_bootstrap_ci is not None
    assert len(summary.paired_bootstrap_ci) == 2


def test_compute_paired_summary_empty():
    summary = compute_paired_summary(
        [],
        task_id="empty",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:0",
    )
    assert summary.total_pairs == 0
    assert math.isnan(summary.paired_bootstrap_ci[0])


def test_paired_evaluation_result_round_trip():
    outcome = PairedSeedOutcome(
        seed=42,
        baseline_success=False,
        candidate_success=True,
        baseline_artifact_dir="/tmp/b",
        candidate_artifact_dir="/tmp/c",
    )
    summary = compute_paired_summary(
        [outcome],
        task_id="round_trip",
        baseline_policy="b",
        candidate_policy="c",
        seed_range="42:43",
    )
    result = PairedEvaluationResult(summary=summary, outcomes=[outcome])
    dumped = result.model_dump()
    loaded = PairedEvaluationResult.model_validate(dumped)
    assert loaded.summary.task_id == "round_trip"
    assert len(loaded.outcomes) == 1
    assert loaded.outcomes[0].delta_class == "rescued"


def test_mcnemar_exact_p_value_monotonic():
    """More discordant evidence should lead to smaller p-values."""
    small = compute_paired_summary(
        [
            PairedSeedOutcome(
                seed=0,
                baseline_success=False,
                candidate_success=True,
                baseline_artifact_dir="b",
                candidate_artifact_dir="c",
            ),
            PairedSeedOutcome(
                seed=1,
                baseline_success=True,
                candidate_success=False,
                baseline_artifact_dir="b",
                candidate_artifact_dir="c",
            ),
        ],
        task_id="small",
        baseline_policy="b",
        candidate_policy="c",
        seed_range="0:2",
    )
    large = compute_paired_summary(
        [
            PairedSeedOutcome(
                seed=i,
                baseline_success=False,
                candidate_success=True,
                baseline_artifact_dir="b",
                candidate_artifact_dir="c",
            )
            for i in range(8)
        ]
        + [
            PairedSeedOutcome(
                seed=i,
                baseline_success=True,
                candidate_success=False,
                baseline_artifact_dir="b",
                candidate_artifact_dir="c",
            )
            for i in range(8, 10)
        ],
        task_id="large",
        baseline_policy="b",
        candidate_policy="c",
        seed_range="0:10",
    )
    assert large.mcnemar_p_value <= small.mcnemar_p_value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
