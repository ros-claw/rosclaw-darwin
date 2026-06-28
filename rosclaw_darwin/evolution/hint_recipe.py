"""HintRecipe: signature-driven adaptive hint generation.

A HintRecipe maps a set of failure-signature tags to a concrete list of skill
hints and optional parameter overrides.  Recipes are ordered by priority and
source trustworthiness, and conflicts are resolved with a small set of domain
rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from rosclaw_darwin.evolution.recovery_hint import RecoveryPolicy


class HintRecipe(BaseModel):
    """A reusable mapping from failure-signature tags to adaptive hints."""

    name: str
    source: str  # manual | auto_rule | mined_from_manual | validated
    trigger_tags: list[str]
    hints: list[str]
    parameter_overrides: dict[str, Any] = {}
    structural_overrides: dict[str, Any] = {}
    strategy_switches: list[str] = []
    recovery_policy: RecoveryPolicy | None = None
    confidence: float = 0.0
    rationale: str | None = None
    expected_effect: str | None = None
    validated_tasks: list[str] = []
    hint_level: str = "local_adaptive_hint"  # local_adaptive_hint | skill_candidate | validated_transferable_skill

    # v3.3 route/claim metadata: honest labeling of what the recipe can claim.
    route_selection: str | None = None  # conditional_micro_recovery | abort_safe | human_escalation | diagnosis_only | blocked_external
    monitor: str | None = None  # grip_quality_monitor | slip_monitor | contact_signal_provider
    claim_level: str = "recovery_candidate"  # diagnosis_only | recovery_candidate | validated
    promotion_status: str = "experimental"  # experimental | boundary_recovery_candidate | validated_transferable_skill | blocked_external

    # v3.4 evidence gate: requirements that must be met before promotion.
    evidence_gate: dict[str, Any] | None = None


# Default conflict-resolution priority.  Lower index = higher precedence.
_RECIPE_PRECEDENCE = [
    "grasp_stability",
    "unstable_grasp",
    "lifted_then_dropped",
    "final_alignment_gap",
    "orientation_gap",
    "not_reached",
]

# Hints that should not be combined.
_INCOMPATIBLE_HINTS: dict[str, set[str]] = {
    "precision_target_tracking": {"stronger_lift", "faster_approach"},
    "slow_final_align": {"faster_approach", "efficient_execution"},
    "stabilize_lift": {"faster_approach", "efficient_execution"},
    "reduce_xy_motion": {"faster_approach", "efficient_execution"},
}


class HintRecipeRegistry:
    """Load, query, and rank HintRecipes."""

    _DEFAULT_PATH: Path = (
        Path(__file__).parent.parent.parent / "configs" / "skills" / "failure_signature_to_hint_rules.yaml"
    )

    def __init__(self, recipes: list[HintRecipe]):
        self.recipes = recipes

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> "HintRecipeRegistry":
        target = Path(path) if path else cls._DEFAULT_PATH
        if not target.exists():
            raise FileNotFoundError(f"Hint recipe rules not found: {target}")
        data = yaml.safe_load(target.read_text())
        if not isinstance(data, dict) or "rules" not in data:
            raise ValueError("Hint recipe rules must contain a 'rules' list")
        recipes = [HintRecipe(**r) for r in data["rules"]]
        return cls(recipes)

    def find_recipes(self, tags: list[str]) -> list[HintRecipe]:
        """Return recipes whose trigger_tags intersect ``tags``.

        Recipes are sorted by:
          1. source trust (validated > auto_rule > mined_from_manual > manual)
          2. confidence (descending)
          3. number of matching tags (descending)
        """
        tag_set = set(tags)
        matched: list[tuple[HintRecipe, int]] = []
        for recipe in self.recipes:
            overlap = tag_set.intersection(recipe.trigger_tags)
            if overlap:
                matched.append((recipe, len(overlap)))

        source_rank = {"validated": 0, "auto_rule": 1, "mined_from_manual": 2, "manual": 3}
        matched.sort(
            key=lambda item: (
                source_rank.get(item[0].source, 99),
                -item[0].confidence,
                -item[1],
                item[0].name,
            )
        )
        return [r for r, _ in matched]

    def select_hints(
        self,
        tags: list[str],
        task_id: str | None = None,
        validated_only: bool = False,
    ) -> tuple[list[str], dict[str, Any], list[HintRecipe]]:
        """Select a deduplicated hint list and merged parameter overrides.

        Returns ``(hints, parameter_overrides, matched_recipes)``.
        """
        recipes = self.find_recipes(tags)
        if validated_only:
            recipes = [r for r in recipes if r.hint_level == "validated_transferable_skill"]

        # Task-specific validated recipes take absolute precedence.
        if task_id:
            task_validated = [r for r in recipes if task_id in r.validated_tasks]
            others = [r for r in recipes if task_id not in r.validated_tasks]
            recipes = task_validated + others

        # Sort recipes by domain precedence to resolve conflicts.
        recipes = _sort_by_precedence(recipes)

        selected_hints: list[str] = []
        selected_set: set[str] = set()
        overrides: dict[str, Any] = {}
        structural_overrides: dict[str, Any] = {}
        strategy_switches: list[str] = []
        matched: list[HintRecipe] = []
        recovery_policy: RecoveryPolicy | None = None

        for recipe in recipes:
            for hint in recipe.hints:
                if hint in selected_set:
                    continue
                if any(hint in _INCOMPATIBLE_HINTS.get(selected, set()) for selected in selected_set):
                    continue
                if any(selected in _INCOMPATIBLE_HINTS.get(hint, set()) for selected in selected_set):
                    continue
                selected_set.add(hint)
                selected_hints.append(hint)
            overrides.update(recipe.parameter_overrides)
            structural_overrides.update(recipe.structural_overrides)
            for switch in recipe.strategy_switches:
                if switch not in strategy_switches:
                    strategy_switches.append(switch)
            if recovery_policy is None and recipe.recovery_policy is not None:
                recovery_policy = recipe.recovery_policy
            matched.append(recipe)

        return selected_hints, overrides, matched, structural_overrides, strategy_switches, recovery_policy


def _sort_by_precedence(recipes: list[HintRecipe]) -> list[HintRecipe]:
    """Stably sort recipes by the first matching precedence tag."""

    def _key(recipe: HintRecipe) -> int:
        for tag in recipe.trigger_tags:
            if tag in _RECIPE_PRECEDENCE:
                return _RECIPE_PRECEDENCE.index(tag)
        return len(_RECIPE_PRECEDENCE)

    return sorted(recipes, key=_key)


def merge_hints(
    signature_hints: list[str],
    manual_hints: list[str] | None = None,
    parameter_overrides: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Merge signature-driven hints with explicit manual hints.

    Manual hints are appended after signature hints, deduplicating while
    preserving order.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for hint in signature_hints:
        if hint not in seen:
            seen.add(hint)
            merged.append(hint)
    for hint in manual_hints or []:
        if hint not in seen:
            seen.add(hint)
            merged.append(hint)
    return merged, dict(parameter_overrides or {})
