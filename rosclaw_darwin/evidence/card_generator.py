"""Evidence card generator for Darwin v1.0."""

from __future__ import annotations

from pathlib import Path

import yaml

from rosclaw_darwin.evolution.evidence_level import EvidenceLevel, EvidenceType
from rosclaw_darwin.schemas.evidence_card import EvidenceCard
from rosclaw_darwin.schemas.intervention import CandidateIntervention
from rosclaw_darwin.schemas.promotion_decision import PromotionDecision
from rosclaw_darwin.schemas.task_validity import TaskValidity


class CardGenerator:
    """Generate productized evidence cards from artifacts or demo mappings."""

    def __init__(self, cards_dir: str | Path = "cards"):
        self.cards_dir = Path(cards_dir)
        self.cards_dir.mkdir(parents=True, exist_ok=True)

    def generate_demo_card(self, candidate_name: str) -> EvidenceCard:
        """Return one of the five v1.0 demo evidence cards."""
        decision = PromotionDecision(
            candidate_name=candidate_name, status="experimental_only"
        )
        if candidate_name == "official_goalpose_baseline":
            decision.status = "v1.0_baseline"
            decision.allowed_claims = ["valid official-asset baseline"]
            return EvidenceCard(
                name=candidate_name,
                type="baseline",
                summary=(
                    "Official dex_cube baseline: 99/100 success, valid environment, "
                    "no fallback."
                ),
                task_validity=TaskValidity(
                    task_id="goal_pose_dex_cube_official",
                    benchmark_scope="official_arena_asset",
                    official_asset=True,
                    can_claim_official_benchmark=True,
                ),
                promotion_decision=decision,
                allowed_claims=[
                    "Darwin can validate benchmark environments and produce clean "
                    "official baselines."
                ],
                blocked_claims=[
                    "universal robot capability is not claimed",
                    "official Arena leaderboard result is not claimed",
                ],
            )
        if candidate_name == "seed24_micro_recovery":
            decision.status = "candidate_recovery"
            return EvidenceCard(
                name=candidate_name,
                type="recovery",
                summary=(
                    "Rescued seeds 24 and 198 without regressing the 0:199 baseline."
                ),
                candidate=CandidateIntervention(
                    name=candidate_name,
                    intervention_type="recovery",
                    status="candidate_recovery",
                ),
                promotion_decision=decision,
                allowed_claims=[
                    "Darwin can promote a candidate recovery based on paired "
                    "no-regression evidence."
                ],
                blocked_claims=[
                    "validated transferable skill is not claimed",
                    "official 100/100 solved is not claimed",
                ],
            )
        if candidate_name == "procedural_fallback_invalid_environment":
            decision.status = "blocked_external"
            return EvidenceCard(
                name=candidate_name,
                type="blocked_external",
                summary="Procedural cube fallback has disabled collision and invalid bbox.",
                task_validity=TaskValidity(
                    task_id="goal_pose_procedural_cube_fallback",
                    benchmark_scope="invalid_environment",
                    validity_status="invalid",
                ),
                promotion_decision=decision,
                allowed_claims=[
                    "Darwin prevents invalid benchmark environments from polluting "
                    "skill evaluation."
                ],
                blocked_claims=[
                    "policy failure on procedural cube is not claimed",
                    "cross-object generalization failure is not claimed",
                ],
            )
        if candidate_name == "large_yaw_torsional_slip_blocked_external":
            decision.status = "blocked_external"
            return EvidenceCard(
                name=candidate_name,
                type="blocked_external",
                summary=(
                    "Large-yaw torsional slip is outside current sensor/control "
                    "capabilities."
                ),
                promotion_decision=decision,
                allowed_claims=[
                    "Darwin can block false recovery promotion and route externally "
                    "blocked failures."
                ],
                blocked_claims=["large-yaw solved is not claimed", "slip recovery validated is not claimed"],
            )
        if candidate_name == "learned_trigger_bounded_residual_experimental":
            decision.status = "experimental_only"
            return EvidenceCard(
                name=candidate_name,
                type="recovery",
                summary=(
                    "Learned trigger + bounded residual is safe but did not rescue "
                    "any seeds."
                ),
                promotion_decision=decision,
                allowed_claims=["Component is implemented and live control is safe."],
                blocked_claims=[
                    "It improves success rate",
                    "It is a promoted recovery",
                ],
            )
        return EvidenceCard(
            name=candidate_name,
            type="recovery",
            summary=f"Evidence card for {candidate_name}.",
            promotion_decision=decision,
        )

    def generate_card(
        self,
        candidate_name: str,
        task_validity: TaskValidity | None = None,
        promotion_decision: PromotionDecision | None = None,
        candidate: CandidateIntervention | None = None,
        artifacts: dict[str, str] | None = None,
        summary: str = "",
        evidence_level: str | None = None,
        evidence_type: str | None = None,
        runtime_eligible: bool = False,
        promotion_scope: str | None = None,
    ) -> EvidenceCard:
        """Build a card from explicit evidence artifacts."""
        decision = promotion_decision or PromotionDecision(
            candidate_name=candidate_name, status="experimental_only"
        )
        return EvidenceCard(
            name=candidate_name,
            candidate=candidate,
            task_validity=task_validity,
            promotion_decision=decision,
            artifacts=artifacts or {},
            summary=summary,
            evidence_level=evidence_level or decision.evidence_level or EvidenceLevel.L0_SYNTHETIC_PIPELINE_DEMO.value,
            evidence_type=evidence_type or decision.evidence_type or EvidenceType.SYNTHETIC.value,
            runtime_eligible=runtime_eligible or decision.runtime_eligible,
            promotion_scope=promotion_scope or decision.promotion_scope,
        )

    def save_card(self, card: EvidenceCard, override: bool = False) -> tuple[Path, Path]:
        """Persist a card as YAML and Markdown."""
        yaml_path = self.cards_dir / f"{card.name}.card.yaml"
        md_path = self.cards_dir / f"{card.name}.card.md"
        if yaml_path.exists() and not override:
            raise FileExistsError(f"Card already exists: {yaml_path}")
        yaml_path.write_text(
            yaml.dump(card.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
        )
        md_path.write_text(render_card_markdown(card))
        return yaml_path, md_path


def render_card_markdown(card: EvidenceCard) -> str:
    """Render an evidence card as Markdown."""
    lines = [
        f"# Evidence Card: {card.name}",
        "",
        f"**Type:** {card.type}",
        f"**Status:** {card.promotion_decision.status}",
        f"**Evidence level:** {card.evidence_level}",
        f"**Evidence type:** {card.evidence_type}",
        f"**Runtime eligible:** {card.runtime_eligible}",
        "",
        "## Summary",
        "",
        card.summary,
        "",
    ]

    if card.task_validity is not None:
        lines.extend([
            "## Task validity",
            "",
            f"- Scope: {card.task_validity.benchmark_scope}",
            f"- Status: {card.task_validity.validity_status}",
            "",
        ])

    if card.candidate is not None:
        lines.extend([
            "## Candidate",
            "",
            f"- Type: {card.candidate.intervention_type}",
            f"- Status: {card.candidate.status}",
            "",
        ])

    lines.extend([
        "## Allowed claims",
        "",
        *(f"- {claim}" for claim in card.allowed_claims),
        "",
        "## Blocked claims",
        "",
        *(f"- {claim}" for claim in card.blocked_claims),
        "",
        "## Limitations",
        "",
        *(f"- {limit}" for limit in card.limitations),
        "",
    ])

    if card.artifacts:
        lines.extend([
            "## Artifacts",
            "",
            *(f"- {name}: {path}" for name, path in card.artifacts.items()),
            "",
        ])

    return "\n".join(lines)


def generate_all_demo_cards(cards_dir: str | Path = "cards") -> list[Path]:
    """Generate the five v1.0 demo cards."""
    generator = CardGenerator(cards_dir)
    names = [
        "official_goalpose_baseline",
        "seed24_micro_recovery",
        "procedural_fallback_invalid_environment",
        "large_yaw_torsional_slip_blocked_external",
        "learned_trigger_bounded_residual_experimental",
    ]
    paths: list[Path] = []
    for name in names:
        card = generator.generate_demo_card(name)
        yaml_path, md_path = generator.save_card(card, override=True)
        paths.extend([yaml_path, md_path])
    return paths


if __name__ == "__main__":
    for p in generate_all_demo_cards():
        print(p)
