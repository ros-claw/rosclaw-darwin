"""Integration tests for Darwin v1.0 dashboard product views."""

from __future__ import annotations

from pathlib import Path

import yaml

from fastapi.testclient import TestClient

from rosclaw_darwin.dashboard.app import DashboardApp


def _make_app(tmp_path: Path) -> DashboardApp:
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    card = {
        "name": "seed24_micro_recovery",
        "type": "recovery",
        "summary": "Seed 24 micro-recovery.",
        "promotion_decision": {"status": "candidate_recovery"},
        "allowed_claims": [],
        "blocked_claims": [],
        "limitations": [],
        "artifacts": {},
    }
    (cards_dir / "seed24_micro_recovery.card.yaml").write_text(yaml.safe_dump(card))

    registry_dir = tmp_path / "data" / "darwin" / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    from rosclaw_darwin.registry import PromotionRegistry

    reg = PromotionRegistry(registry_dir)
    reg.add("seed24_micro_recovery", kind="recovery", status="candidate_recovery", card="seed24_micro_recovery.card.yaml")

    return DashboardApp(data_dir=str(tmp_path / "data"))


def test_overview_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "ROSClaw-Darwin v1.0" in response.text
    assert "Evidence engine" in response.text


def test_validity_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/validity")
    assert response.status_code == 200
    assert "Benchmark Validity" in response.text


def test_baselines_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/baselines")
    assert response.status_code == 200
    assert "Official Baselines" in response.text


def test_paired_evaluations_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/paired-evaluations")
    assert response.status_code == 200
    assert "Paired No-Regression" in response.text


def test_promotions_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/promotions")
    assert response.status_code == 200
    assert "Promotion Decisions" in response.text


def test_evidence_cards_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/evidence-cards")
    assert response.status_code == 200
    assert "seed24_micro_recovery" in response.text


def test_registry_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/registry")
    assert response.status_code == 200
    assert "Promotion Registry" in response.text
    assert "seed24_micro_recovery" in response.text


def test_blocked_external_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/blocked-external")
    assert response.status_code == 200
    assert "Blocked External" in response.text


def test_demos_page_renders(tmp_path: Path):
    app = _make_app(tmp_path)
    client = TestClient(app.app)
    response = client.get("/demos")
    assert response.status_code == 200
    assert "v1.0 Demo Pack" in response.text
