"""Unit tests for claim boundary linter."""

from __future__ import annotations

from pathlib import Path

from scripts.quality.check_claim_boundaries import (
    check_evidence_cards,
    scan_text,
)


def test_scan_text_detects_unsupported_phrase(tmp_path: Path):
    text = "This result proves validated transferable skill across objects."
    violations = scan_text(text, ["validated transferable skill"])
    assert len(violations) == 1
    assert violations[0][0] == "validated transferable skill"


def test_scan_text_ignores_case(tmp_path: Path):
    text = "Large-Yaw SOLVED is a headline we must reject."
    violations = scan_text(text, ["large-yaw solved"])
    assert len(violations) == 1


def test_scan_text_no_violation():
    text = "Candidate recovery is supported by paired evidence."
    violations = scan_text(text, ["validated transferable skill"])
    assert violations == []


def test_check_evidence_cards_missing(tmp_path: Path):
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    (cards_dir / "seed24_micro_recovery.card.yaml").write_text("name: seed24")
    errors = check_evidence_cards(cards_dir, ["seed24_micro_recovery", "missing_card"])
    assert len(errors) == 1
    assert "missing_card" in errors[0]


def test_check_evidence_cards_all_present(tmp_path: Path):
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    for name in ["a", "b"]:
        (cards_dir / f"{name}.card.yaml").write_text(f"name: {name}")
    errors = check_evidence_cards(cards_dir, ["a", "b"])
    assert errors == []
