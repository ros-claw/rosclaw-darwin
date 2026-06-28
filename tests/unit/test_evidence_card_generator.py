"""Unit tests for the Darwin v1.0 evidence card generator."""

from __future__ import annotations

import yaml

from rosclaw_darwin.evidence import CardGenerator, generate_all_demo_cards
from rosclaw_darwin.schemas.promotion_decision import PromotionDecision
from rosclaw_darwin.schemas.task_validity import TaskValidity


def test_generate_demo_card_seed24():
    generator = CardGenerator("/tmp/rosclaw_test_cards")
    card = generator.generate_demo_card("seed24_micro_recovery")
    assert card.name == "seed24_micro_recovery"
    assert card.type == "recovery"
    assert card.promotion_decision.status == "candidate_recovery"
    assert "validated transferable skill is not claimed" in card.blocked_claims


def test_generate_demo_card_procedural_invalid():
    generator = CardGenerator("/tmp/rosclaw_test_cards")
    card = generator.generate_demo_card("procedural_fallback_invalid_environment")
    assert card.type == "blocked_external"
    assert card.task_validity is not None
    assert card.task_validity.validity_status == "invalid"


def test_save_card(tmp_path):
    generator = CardGenerator(tmp_path)
    card = generator.generate_demo_card("official_goalpose_baseline")
    yaml_path, md_path = generator.save_card(card)
    assert yaml_path.exists()
    assert md_path.exists()
    data = yaml.safe_load(yaml_path.read_text())
    assert data["name"] == "official_goalpose_baseline"


def test_generate_all_demo_cards(tmp_path):
    paths = generate_all_demo_cards(tmp_path)
    assert len(paths) == 10  # 5 cards x 2 formats
    names = {p.stem.replace(".card", "") for p in paths}
    assert "seed24_micro_recovery" in names
    assert "procedural_fallback_invalid_environment" in names


def test_render_markdown_contains_blocked_claims():
    generator = CardGenerator("/tmp/rosclaw_test_cards")
    card = generator.generate_demo_card("large_yaw_torsional_slip_blocked_external")
    from rosclaw_darwin.evidence.card_generator import render_card_markdown

    text = render_card_markdown(card)
    assert "large-yaw solved" in text
    assert "Evidence Card: large_yaw_torsional_slip_blocked_external" in text


def test_generate_card_from_artifacts():
    generator = CardGenerator("/tmp/rosclaw_test_cards")
    decision = PromotionDecision(
        candidate_name="custom", status="experimental_only"
    )
    validity = TaskValidity(
        task_id="custom_task",
        benchmark_scope="rosclaw_ood_diagnostic",
        validity_status="valid",
    )
    card = generator.generate_card(
        "custom",
        promotion_decision=decision,
        task_validity=validity,
        artifacts={"summary": "data/summary.json"},
    )
    assert card.name == "custom"
    assert card.task_validity.benchmark_scope == "rosclaw_ood_diagnostic"
    assert card.artifacts["summary"] == "data/summary.json"
