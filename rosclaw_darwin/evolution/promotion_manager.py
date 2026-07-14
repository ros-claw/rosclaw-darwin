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

    def __init__(
        self,
        paired_eval: PairedEvaluationSummary | None = None,
        paired_summary_dict: dict[str, Any] | None = None,
    ):
        """Initialize with an optional paired-evaluation summary.

        ``None`` means no paired evidence is available; every gatable recipe
        will be downgraded to ``experimental_only``.
        """
        self.paired_eval = paired_eval
        self.paired_summary_dict = paired_summary_dict

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

        if gate_type == "continuous_metric_rescue":
            return self._evaluate_continuous_metric_rescue(recipe, gate)

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

    def _evaluate_continuous_metric_rescue(
        self,
        recipe: HintRecipe,
        gate: dict[str, Any],
    ) -> EvidenceStatus:
        """Evaluate a continuous-metric rescue gate from an offline paired summary."""
        summary = self.paired_summary_dict
        if summary is None:
            return EvidenceStatus(
                recipe_name=recipe.name,
                route_selection=recipe.route_selection,
                promotion_status="experimental_only",
                evidence_gate_passed=False,
                gate_reason="continuous_metric_rescue gate requires a paired summary dict (none provided).",
                required_evidence=gate,
            )

        summary_dict = dict(summary)

        min_seeds = int(gate.get("min_seeds", 1))
        min_improved = int(gate.get("min_improved_seeds", 1))
        max_regressed = int(gate.get("max_newly_regressed", 0))
        mean_final_threshold = gate.get("mean_final_threshold")
        mean_delta_threshold = gate.get("mean_delta_threshold")
        mean_action_norm_max = gate.get("mean_action_norm_max")

        reasons: list[str] = []
        passed = True

        valid_pairs = int(summary_dict.get("valid_pairs", 0))
        if valid_pairs < min_seeds:
            reasons.append(f"valid_pairs={valid_pairs} < min={min_seeds}")
            passed = False

        improved = int(summary_dict.get("metric_improved_count", 0))
        if improved < min_improved:
            reasons.append(f"metric_improved_count={improved} < min={min_improved}")
            passed = False

        regressed = int(summary_dict.get("metric_regressed_count", 0))
        if regressed > max_regressed:
            reasons.append(f"metric_regressed_count={regressed} > max={max_regressed}")
            passed = False

        baseline = summary_dict.get("baseline", {})
        candidate = summary_dict.get("candidate", {})
        metric = summary_dict.get("metric", "eef_to_object_distance")

        b_final = baseline.get("eef_to_object_distance_final_mean") if metric != "action_norm" else baseline.get("mean_action_norm")
        c_final = candidate.get("eef_to_object_distance_final_mean") if metric != "action_norm" else candidate.get("mean_action_norm")
        if b_final is not None and c_final is not None:
            if metric == "action_norm":
                if c_final > b_final:
                    reasons.append(f"candidate_action_norm={c_final:.4f} > baseline={b_final:.4f}")
                    passed = False
            else:
                if c_final >= b_final:
                    reasons.append(f"candidate_final={c_final:.4f} >= baseline={b_final:.4f}")
                    passed = False
            if mean_final_threshold is not None and c_final > mean_final_threshold:
                reasons.append(f"candidate_final={c_final:.4f} > threshold={mean_final_threshold}")
                passed = False

        b_delta = baseline.get("distance_reduction_mean") if metric != "action_norm" else None
        c_delta = candidate.get("distance_reduction_mean") if metric != "action_norm" else None
        if b_delta is not None and c_delta is not None and mean_delta_threshold is not None:
            if c_delta <= b_delta + mean_delta_threshold:
                reasons.append(f"candidate_delta={c_delta:.4f} <= baseline_delta={b_delta:.4f} + threshold={mean_delta_threshold}")
                passed = False

        c_action_norm = candidate.get("mean_action_norm")
        if c_action_norm is not None and mean_action_norm_max is not None:
            if c_action_norm > mean_action_norm_max:
                reasons.append(f"candidate_action_norm={c_action_norm:.4f} > max={mean_action_norm_max}")
                passed = False

        if passed:
            promotion_status = "real_adapter_fix_recovery"
            gate_reason = "continuous_metric_rescue gate passed"
        else:
            promotion_status = "experimental_only"
            gate_reason = "continuous_metric_rescue gate failed: " + "; ".join(reasons)

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
