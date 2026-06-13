"""Generate skill hints from observed failure types."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from rosclaw_darwin.evaluation.result import EvaluationResult


class SkillHint(BaseModel):
    name: str
    source: str  # auto_from_failure | manual | validated_skill
    source_failure_type: str | None = None
    confidence: float
    rationale: str | None = None


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

    def to_dict(self, hints: list[SkillHint]) -> list[dict[str, Any]]:
        return [h.model_dump(mode="json") for h in hints]
