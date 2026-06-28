"""Evidence-aware promotion status for FailureToHint v3.4.

``EvidenceStatus`` is the public outcome of applying a promotion gate to a
``HintRecipe``.  It records whether the recipe is allowed to claim recovery
success, remain experimental, or be blocked because the failure mechanism is
outside the policy's control.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidenceStatus(BaseModel):
    """Promotion decision for a single ``HintRecipe``.

    Attributes
    ----------
    recipe_name:
        Name of the recipe being evaluated.
    route_selection:
        The recipe's selected recovery route (e.g. ``blocked_external``).
    promotion_status:
        One of ``blocked_external``, ``experimental_only``,
        ``candidate_recovery``, ``validated_recovery``, or ``human_escalation``.
    evidence_gate_passed:
        ``True`` iff the recipe meets its declared evidence gate.
    gate_reason:
        Human-readable explanation of the promotion decision.
    paired_summary:
        Optional snapshot of the paired-evaluation summary used for the gate.
    required_evidence:
        The evidence-gate requirements declared by the recipe.
    """

    recipe_name: str
    route_selection: str | None = None
    promotion_status: str
    evidence_gate_passed: bool
    gate_reason: str
    paired_summary: dict[str, Any] | None = None
    required_evidence: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return self.model_dump(mode="json")
