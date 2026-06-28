"""Integration test for paired evaluation JSON report schema."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from rosclaw_darwin.evaluation.paired_evaluation import (
    PairedEvaluationResult,
    PairedSeedOutcome,
    compute_paired_summary,
)


def test_paired_eval_report_schema_round_trip():
    """Write a paired summary to disk and validate it round-trips."""
    outcomes = [
        PairedSeedOutcome(
            seed=0,
            baseline_success=True,
            candidate_success=True,
            baseline_artifact_dir="/tmp/b0",
            candidate_artifact_dir="/tmp/c0",
        ),
        PairedSeedOutcome(
            seed=1,
            baseline_success=False,
            candidate_success=True,
            baseline_failure_type="grip_force_insufficient",
            candidate_failure_type=None,
            baseline_artifact_dir="/tmp/b1",
            candidate_artifact_dir="/tmp/c1",
        ),
        PairedSeedOutcome(
            seed=2,
            baseline_success=True,
            candidate_success=False,
            baseline_failure_type=None,
            candidate_failure_type="object_slipped_during_lift",
            baseline_artifact_dir="/tmp/b2",
            candidate_artifact_dir="/tmp/c2",
        ),
    ]
    summary = compute_paired_summary(
        outcomes,
        task_id="integration_test",
        baseline_policy="frozen_baseline",
        candidate_policy="candidate_v1",
        seed_range="0:3",
    )
    result = PairedEvaluationResult(summary=summary, outcomes=outcomes)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "paired_result.json"
        path.write_text(json.dumps(result.model_dump(), indent=2))
        loaded = PairedEvaluationResult.model_validate(json.loads(path.read_text()))

    assert loaded.summary.task_id == "integration_test"
    assert loaded.summary.rescued_count == 1
    assert loaded.summary.newly_failed_count == 1
    assert loaded.summary.net_delta == 0
    assert len(loaded.outcomes) == 3
    assert loaded.outcomes[1].delta_class == "rescued"
    assert loaded.outcomes[2].delta_class == "newly_failed"


def test_paired_eval_summary_csv_columns():
    """Summary can be flattened to a CSV-friendly dict."""
    outcome = PairedSeedOutcome(
        seed=7,
        baseline_success=False,
        candidate_success=True,
        baseline_artifact_dir="/tmp/b",
        candidate_artifact_dir="/tmp/c",
    )
    summary = compute_paired_summary(
        [outcome],
        task_id="csv_test",
        baseline_policy="b",
        candidate_policy="c",
        seed_range="7:8",
    )
    flat = summary.model_dump()
    required = {
        "task_id",
        "baseline_policy",
        "candidate_policy",
        "seed_range",
        "total_pairs",
        "valid_pairs",
        "rescued_count",
        "newly_failed_count",
        "net_delta",
        "mcnemar_p_value",
        "paired_bootstrap_ci",
    }
    assert required.issubset(flat.keys())


def test_paired_eval_invalid_pair_handling():
    """Invalid pairs are excluded from rates but counted."""
    outcomes = [
        PairedSeedOutcome(
            seed=0,
            baseline_success=False,
            candidate_success=False,
            baseline_artifact_dir="/tmp/b",
            candidate_artifact_dir="/tmp/c",
        ),
        PairedSeedOutcome(
            seed=1,
            baseline_success=True,
            candidate_success=True,
            baseline_artifact_dir="/tmp/b",
            candidate_artifact_dir="/tmp/c",
            notes=["invalid_pair"],
        ),
    ]
    summary = compute_paired_summary(
        outcomes,
        task_id="invalid_test",
        baseline_policy="b",
        candidate_policy="c",
        seed_range="0:2",
    )
    assert summary.total_pairs == 2
    assert summary.valid_pairs == 1
    assert summary.invalid_pair_count == 1
    assert summary.baseline_success_rate == 0.0
    assert summary.candidate_success_rate == 0.0


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
