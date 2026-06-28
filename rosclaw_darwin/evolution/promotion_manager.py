"""Evidence-aware promotion manager for FailureToHint v3.4.

``PromotionManager`` consumes a ``PairedEvaluationSummary`` and a
``HintRecipe`` and returns an ``EvidenceStatus`` that prevents unverified
recovery claims from being promoted.
"""

from __future__ import annotations

from typing import Any

from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.evolution.evidence_status import EvidenceStatus
from rosclaw_darwin.evolution.hint_recipe import HintRecipe


class PromotionManager:
    """Decide whether a recipe's promotion status is supported by evidence."""

    def __init__(self, paired_eval: PairedEvaluationSummary | None = None):
        """Initialize with an optional paired-evaluation summary.

        ``None`` means no paired evidence is available; every gatable recipe
        will be downgraded to ``experimental_only``.
        """
        self.paired_eval = paired_eval

    def evaluate(self, recipe: HintRecipe) -> EvidenceStatus:
        """Return the evidence-aware promotion status for ``recipe``."""
        route = recipe.route_selection
        gate = recipe.evidence_gate or {}

        # Hard blocks: routes that are explicitly outside the policy's control.
        if route == "blocked_external":
            return EvidenceStatus(
                recipe_name=recipe.name,
                route_selection=route,
                promotion_status="blocked_external",
                evidence_gate_passed=False,
                gate_reason="Route is outside the policy's control (blocked_external).",
                required_evidence=gate,
            )

        if route in {"abort_safe", "human_escalation"}:
            return EvidenceStatus(
                recipe_name=recipe.name,
                route_selection=route,
                promotion_status="human_escalation",
                evidence_gate_passed=False,
                gate_reason=f"Route '{route}' requires human review before any promotion.",
                required_evidence=gate,
            )

        # If the recipe declares no evidence gate, keep it experimental.
        if not gate:
            return EvidenceStatus(
                recipe_name=recipe.name,
                route_selection=route,
                promotion_status="experimental_only",
                evidence_gate_passed=False,
                gate_reason="No evidence_gate declared; recipe remains experimental.",
                required_evidence=gate,
            )

        gate_type = gate.get("gate_type")

        if gate_type == "paired_no_regression":
            return self._evaluate_paired_no_regression(recipe, gate)

        # Unknown gate type: stay experimental to avoid false promotion.
        return EvidenceStatus(
            recipe_name=recipe.name,
            route_selection=route,
            promotion_status="experimental_only",
            evidence_gate_passed=False,
            gate_reason=f"Unknown evidence_gate type '{gate_type}'; recipe remains experimental.",
            required_evidence=gate,
        )

    def _evaluate_paired_no_regression(
        self,
        recipe: HintRecipe,
        gate: dict[str, Any],
    ) -> EvidenceStatus:
        """Evaluate a paired no-regression gate."""
        if self.paired_eval is None:
            return EvidenceStatus(
                recipe_name=recipe.name,
                route_selection=recipe.route_selection,
                promotion_status="experimental_only",
                evidence_gate_passed=False,
                gate_reason="paired_no_regression gate requires a PairedEvaluationSummary (none provided).",
                required_evidence=gate,
            )

        min_rescued = int(gate.get("min_rescued_count", 1))
        max_newly_failed = int(gate.get("max_newly_failed_count", 0))
        min_candidate_rate = float(gate.get("min_candidate_success_rate", 0.0))
        max_new_failure_rate = float(gate.get("max_new_failure_rate", 1.0))

        summary = self.paired_eval
        summary_dict = summary.model_dump(mode="json")

        reasons: list[str] = []
        passed = True

        if summary.rescued_count < min_rescued:
            reasons.append(
                f"rescued_count={summary.rescued_count} < min={min_rescued}"
            )
            passed = False
        if summary.newly_failed_count > max_newly_failed:
            reasons.append(
                f"newly_failed_count={summary.newly_failed_count} > max={max_newly_failed}"
            )
            passed = False
        if summary.candidate_success_rate < min_candidate_rate:
            reasons.append(
                f"candidate_success_rate={summary.candidate_success_rate} < min={min_candidate_rate}"
            )
            passed = False
        baseline_successes = summary.valid_pairs - int(
            summary.valid_pairs * summary.baseline_success_rate
        )
        # Avoid division by zero when baseline never succeeded.
        denom = max(baseline_successes, 1)
        observed_new_failure_rate = summary.newly_failed_count / denom
        if observed_new_failure_rate > max_new_failure_rate:
            reasons.append(
                f"observed_new_failure_rate={observed_new_failure_rate:.3f} > max={max_new_failure_rate}"
            )
            passed = False

        if passed:
            promotion_status = "candidate_recovery"
            gate_reason = "paired_no_regression gate passed"
        else:
            promotion_status = "experimental_only"
            gate_reason = "paired_no_regression gate failed: " + "; ".join(reasons)

        return EvidenceStatus(
            recipe_name=recipe.name,
            route_selection=recipe.route_selection,
            promotion_status=promotion_status,
            evidence_gate_passed=passed,
            gate_reason=gate_reason,
            paired_summary=summary_dict,
            required_evidence=gate,
        )

    @classmethod
    def from_summary_dict(cls, data: dict[str, Any] | None) -> "PromotionManager":
        """Build a manager from a raw paired-evaluation summary dict."""
        if data is None:
            return cls(None)
        summary = PairedEvaluationSummary.model_validate(data)
        return cls(summary)
