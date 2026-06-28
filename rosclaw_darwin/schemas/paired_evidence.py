"""Paired evidence schema re-export for Darwin v1.0."""

from __future__ import annotations

from rosclaw_darwin.evaluation.paired_evaluation import (
    PairedEvaluationResult,
    PairedEvaluationSummary,
    PairedSeedOutcome,
    classify_pair,
    compute_paired_summary,
)

__all__ = [
    "PairedEvaluationResult",
    "PairedEvaluationSummary",
    "PairedSeedOutcome",
    "classify_pair",
    "compute_paired_summary",
]
