"""Generate skill hints from observed failure types."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evolution.evidence_status import EvidenceStatus
from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry
from rosclaw_darwin.evolution.promotion_manager import PromotionManager
from rosclaw_darwin.evolution.recovery_hint import RecoveryPolicy


class SkillHint(BaseModel):
    name: str
    source: str  # auto_from_failure | auto_from_signature_v3 | manual | validated_skill
    source_failure_type: str | None = None
    source_recipe: str | None = None
    confidence: float
    rationale: str | None = None
    parameter_overrides: dict[str, Any] = {}
    structural_overrides: dict[str, Any] = {}
    strategy_switches: list[str] = []
    recovery_policy: RecoveryPolicy | None = None

    # v3.3 route selection and claim-level metadata.
    route_selection: str | None = None
    monitor: str | None = None
    claim_level: str = "recovery_candidate"
    promotion_status: str | None = None

    # v3.4 evidence-aware promotion snapshot.
    evidence_status: dict[str, Any] | None = None




def select_recovery_route(
    tags: list[str],
    recipe_registry: HintRecipeRegistry | None = None,
    task_id: str | None = None,
) -> dict[str, Any | None]:
    """Select a recovery route and claim level from FailureSignature v3 tags.

    The route is chosen from the highest-priority matched recipe that defines a
    ``route_selection``.  If no recipe defines a route, a small set of tag-based
    defaults is used so that the engine never silently claims a recovery it
    cannot perform.
    """
    registry = recipe_registry or HintRecipeRegistry.from_yaml()
    recipes = registry.find_recipes(tags)
    if task_id:
        task_specific = [r for r in recipes if task_id in r.validated_tasks]
        others = [r for r in recipes if task_id not in r.validated_tasks]
        recipes = task_specific + others

    routed = [r for r in recipes if r.route_selection is not None]
    if routed:
        recipe = routed[0]
        return {
            "route_selection": recipe.route_selection,
            "monitor": recipe.monitor,
            "claim_level": recipe.claim_level,
            "promotion_status": recipe.promotion_status,
        }

    tag_set = set(tags)
    seed24_tags = {
        "grip_force_insufficient",
        "low_object_z_at_grasp",
        "gripper_too_open",
    }
    if seed24_tags.intersection(tag_set):
        return {
            "route_selection": "conditional_micro_recovery",
            "monitor": "grip_quality_monitor",
            "claim_level": "recovery_candidate",
            "promotion_status": "experimental",
        }

    large_yaw_tags = {
        "large_yaw_torsional_slip",
        "rotation_induced_slip",
        "yaw_not_transferred_to_object",
    }
    if large_yaw_tags.intersection(tag_set):
        return {
            "route_selection": "blocked_external",
            "monitor": "slip_monitor",
            "claim_level": "diagnosis_only",
            "promotion_status": "blocked_external",
        }

    return {
        "route_selection": "diagnosis_only",
        "monitor": None,
        "claim_level": "diagnosis_only",
        "promotion_status": "experimental",
    }

class FailureToHintRule(BaseModel):
    failure_type: str
    hints: list[str]
    confidence: float
    rationale: str


class FailureToHintEngine:
    """Suggest skill hints based on failure type counts and a YAML rule file."""

    _DEFAULT_PATH: Path = Path(__file__).parent.parent.parent / "configs" / "skills" / "failure_to_hint_rules.yaml"

    def __init__(self, rules: list[FailureToHintRule]):
        self.rules = {r.failure_type: r for r in rules}

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> "FailureToHintEngine":
        target = Path(path) if path else cls._DEFAULT_PATH
        if not target.exists():
            raise FileNotFoundError(f"Failure-to-hint rules not found: {target}")
        data = yaml.safe_load(target.read_text())
        if not isinstance(data, dict) or "rules" not in data:
            raise ValueError("Failure-to-hint rules must contain a 'rules' list")
        rules = [FailureToHintRule(**r) for r in data["rules"]]
        return cls(rules)

    def suggest(self, failure_types: dict[str, int]) -> list[SkillHint]:
        """Return ordered skill hints for observed failure types.

        Only failure types with a positive count are considered. Hints are
        deduplicated while preserving the order of the most confident rule first.
        """
        hints: list[SkillHint] = []
        seen: set[str] = set()

        # Process failure types ordered by descending count so frequent failures dominate.
        sorted_failures = sorted(failure_types.items(), key=lambda x: x[1], reverse=True)
        for failure_type, count in sorted_failures:
            if count <= 0:
                continue
            rule = self.rules.get(failure_type)
            if not rule:
                continue
            for hint_name in rule.hints:
                if hint_name in seen:
                    continue
                seen.add(hint_name)
                hints.append(
                    SkillHint(
                        name=hint_name,
                        source="auto_from_failure",
                        source_failure_type=failure_type,
                        confidence=rule.confidence,
                        rationale=rule.rationale,
                    )
                )
        return hints

    def suggest_from_result(self, result: EvaluationResult) -> list[SkillHint]:
        return self.suggest(result.failure_types)

    def suggest_from_signatures(
        self,
        signatures: list[Any],
        recipe_registry: HintRecipeRegistry | None = None,
        task_id: str | None = None,
        paired_summary: Any = None,
    ) -> list[SkillHint]:
        """Suggest skill hints from rich FailureSignature v3 tags.

        Collects all ``signature_tags`` / ``hint_relevant_tags`` from the
        signatures, queries the ``HintRecipeRegistry``, and returns hints
        together with the merged ``parameter_overrides`` from matched recipes.
        Falls back to the coarse failure-type engine if no signature tags are
        available.

        If ``paired_summary`` is provided, each matched recipe is evaluated
        through the v3.4 ``PromotionManager`` and the resulting
        ``evidence_status`` is attached to the hint.
        """
        from rosclaw_darwin.evaluation.failure_signature import FailureSignature

        tags: list[str] = []
        for sig in signatures:
            if isinstance(sig, FailureSignature):
                tags.extend(sig.signature_tags or [])
                tags.extend(sig.hint_relevant_tags or [])
            elif isinstance(sig, dict):
                tags.extend(sig.get("signature_tags") or [])
                tags.extend(sig.get("hint_relevant_tags") or [])

        if not tags and signatures:
            # Fallback: use failure_type strings if no rich tags are present.
            failure_types: dict[str, int] = {}
            for sig in signatures:
                if isinstance(sig, FailureSignature):
                    failure_types[sig.failure_type] = failure_types.get(sig.failure_type, 0) + 1
                elif isinstance(sig, dict):
                    failure_types[sig.get("failure_type", "unknown")] = failure_types.get(
                        sig.get("failure_type", "unknown"), 0
                    ) + 1
            return self.suggest(failure_types)

        registry = recipe_registry or HintRecipeRegistry.from_yaml()
        selected, overrides, matched, structural_overrides, strategy_switches, recovery_policy = registry.select_hints(
            tags, task_id=task_id
        )

        if paired_summary is not None:
            manager = PromotionManager.from_summary_dict(paired_summary)
            statuses = {recipe.name: manager.evaluate(recipe) for recipe in matched}
        else:
            statuses = {}

        hints: list[SkillHint] = []
        seen: set[str] = set()
        for recipe in matched:
            status = statuses.get(recipe.name)
            for hint_name in recipe.hints:
                if hint_name in seen:
                    continue
                seen.add(hint_name)
                hints.append(
                    SkillHint(
                        name=hint_name,
                        source="auto_from_signature_v3",
                        source_recipe=recipe.name,
                        confidence=recipe.confidence,
                        rationale=recipe.rationale,
                        parameter_overrides=dict(overrides),
                        structural_overrides=dict(structural_overrides),
                        strategy_switches=list(strategy_switches),
                        recovery_policy=recovery_policy,
                        route_selection=recipe.route_selection,
                        monitor=recipe.monitor,
                        claim_level=recipe.claim_level,
                        promotion_status=(
                            status.promotion_status
                            if status is not None
                            else recipe.promotion_status
                        ),
                        evidence_status=status.to_dict() if status is not None else None,
                    )
                )
        return hints

    def evaluate_recipe_evidence(
        self,
        signatures: list[Any],
        paired_summary: Any = None,
        recipe_registry: HintRecipeRegistry | None = None,
        task_id: str | None = None,
    ) -> list[EvidenceStatus]:
        """Return the v3.4 ``EvidenceStatus`` for every matched recipe.

        This is the public entry point for evidence-aware promotion.  It does
        not produce hints; it only checks whether each matched recipe's claimed
        recovery route is supported by the provided paired-evaluation summary.
        """
        from rosclaw_darwin.evaluation.failure_signature import FailureSignature

        tags: list[str] = []
        for sig in signatures:
            if isinstance(sig, FailureSignature):
                tags.extend(sig.signature_tags or [])
                tags.extend(sig.hint_relevant_tags or [])
            elif isinstance(sig, dict):
                tags.extend(sig.get("signature_tags") or [])
                tags.extend(sig.get("hint_relevant_tags") or [])

        if not tags:
            return []

        registry = recipe_registry or HintRecipeRegistry.from_yaml()
        _, _, matched, _, _, _ = registry.select_hints(tags, task_id=task_id)
        manager = (
            PromotionManager.from_summary_dict(paired_summary)
            if paired_summary is not None
            else PromotionManager(None)
        )
        return [manager.evaluate(recipe) for recipe in matched]

    def to_dict(self, hints: list[SkillHint]) -> list[dict[str, Any]]:
        return [h.model_dump(mode="json") for h in hints]
