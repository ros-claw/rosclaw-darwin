"""ManualHintMiner: turn effective manual hints into candidate v2 rules.

When a manual-hints condition outperforms the no-hint baseline, this module
proposes a candidate ``HintRecipe`` that maps the baseline failure signature
tags to the manual hints that apparently helped.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evolution.hint_recipe import HintRecipe


def _signature_tags(signatures: list[FailureSignature]) -> list[str]:
    """Collect all signature tags from a list of episode signatures."""
    tags: list[str] = []
    for sig in signatures:
        if not sig.success:
            tags.extend(sig.signature_tags)
    return tags


def _compute_gain(
    baseline_metric: float,
    variant_metric: float,
    metric_name: str = "progress",
) -> dict[str, Any]:
    """Return a small gain description."""
    return {
        "metric": metric_name,
        "baseline": round(baseline_metric, 6),
        "variant": round(variant_metric, 6),
        "absolute_gain": round(variant_metric - baseline_metric, 6),
        "relative_gain": round((variant_metric - baseline_metric) / baseline_metric, 6) if baseline_metric else None,
    }


def mine_candidate_rules(
    task_id: str,
    baseline_signatures: list[FailureSignature],
    variant_signatures: list[FailureSignature],
    manual_hints: list[str],
    baseline_progress: float = 0.0,
    variant_progress: float = 0.0,
    baseline_success_rate: float = 0.0,
    variant_success_rate: float = 0.0,
    progress_gain_threshold: float = 0.01,
    success_gain_threshold: float = 0.0,
) -> list[HintRecipe]:
    """Generate candidate HintRecipes from a manual-hint improvement.

    A rule is generated only when the manual variant improves over baseline by
    at least one of the thresholds.  The candidate is marked
    ``requires_validation`` implicitly by setting ``hint_level`` to
    ``skill_candidate`` and source to ``mined_from_manual``.
    """
    progress_gain = variant_progress - baseline_progress
    success_gain = variant_success_rate - baseline_success_rate

    improved = (
        progress_gain >= progress_gain_threshold
        or success_gain > success_gain_threshold
    )
    if not improved:
        return []

    baseline_tags = _signature_tags(baseline_signatures)
    variant_tags = _signature_tags(variant_signatures)

    # Focus on tags that are frequent in the baseline and reduced in the variant.
    baseline_counts = Counter(baseline_tags)
    variant_counts = Counter(variant_tags)
    candidate_tags: list[str] = []
    for tag, count in baseline_counts.most_common(10):
        if count >= 2 and variant_counts.get(tag, 0) < count:
            candidate_tags.append(tag)

    # If no tag reduced, still use the most common baseline tag.
    if not candidate_tags and baseline_counts:
        candidate_tags = [baseline_counts.most_common(1)[0][0]]

    if not candidate_tags:
        return []

    gain = _compute_gain(baseline_progress, variant_progress, metric_name="progress")
    gain_success = _compute_gain(baseline_success_rate, variant_success_rate, metric_name="success_rate")

    recipe = HintRecipe(
        name=f"mined_{task_id}_{'_'.join(candidate_tags[:3])}",
        source="mined_from_manual",
        hint_level="skill_candidate",
        trigger_tags=candidate_tags,
        hints=list(manual_hints),
        confidence=round(min(0.5 + max(progress_gain, success_gain), 0.95), 4),
        rationale=(
            f"Mined from manual-hints improvement on {task_id}: "
            f"progress gain {gain['absolute_gain']}, success-rate gain {gain_success['absolute_gain']}."
        ),
        expected_effect="Improve the metrics observed under manual hints.",
        validated_tasks=[],
    )
    return [recipe]


def mine_candidate_rules_from_ablation(
    task_id: str,
    baseline_signatures: list[FailureSignature],
    manual_signatures: list[FailureSignature],
    auto_signatures: list[FailureSignature],
    manual_hints: list[str],
    baseline_progress: float = 0.0,
    manual_progress: float = 0.0,
    auto_progress: float = 0.0,
    baseline_success_rate: float = 0.0,
    manual_success_rate: float = 0.0,
    auto_success_rate: float = 0.0,
) -> dict[str, Any]:
    """Convenience wrapper that mines rules and reports whether auto also improved.

    Returns a dict with ``candidate_rules`` and ``comparison`` metadata.
    """
    candidates = mine_candidate_rules(
        task_id=task_id,
        baseline_signatures=baseline_signatures,
        variant_signatures=manual_signatures,
        manual_hints=manual_hints,
        baseline_progress=baseline_progress,
        variant_progress=manual_progress,
        baseline_success_rate=baseline_success_rate,
        variant_success_rate=manual_success_rate,
    )

    comparison = {
        "manual_vs_baseline": {
            "delta_progress": round(manual_progress - baseline_progress, 6),
            "delta_success_rate": round(manual_success_rate - baseline_success_rate, 6),
        },
        "auto_vs_baseline": {
            "delta_progress": round(auto_progress - baseline_progress, 6),
            "delta_success_rate": round(auto_success_rate - baseline_success_rate, 6),
        },
        "manual_better_than_auto": (
            (manual_progress > auto_progress) or (manual_success_rate > auto_success_rate)
        ),
    }

    return {
        "task_id": task_id,
        "candidate_rules": [r.model_dump(mode="json") for r in candidates],
        "comparison": comparison,
    }
