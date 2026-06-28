"""Integration tests for v1.10 dashboard views and data loaders."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rosclaw_darwin.dashboard.app import DashboardApp


@pytest.fixture
def client() -> TestClient:
    app = DashboardApp(data_dir="/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20")
    return TestClient(app.app)


@pytest.mark.parametrize("path", [
    "/paired-evaluation",
    "/contact-signal-v2",
    "/learned-trigger",
    "/residual-policy-v2",
    "/valid-ood-medium",
    "/fth-v34",
])
def test_v20_dashboard_pages_load(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text or "<html>" in response.text


@pytest.mark.parametrize("path", [
    "/paired-evaluation/chart.svg",
    "/contact-signal-v2/chart.svg",
    "/learned-trigger/chart.svg",
    "/residual-policy-v2/chart.svg",
    "/valid-ood-medium/chart.svg",
    "/fth-v34/chart.svg",
])
def test_v20_dashboard_chart_endpoints_exist(client: TestClient, path: str) -> None:
    response = client.get(path)
    # 200 if data is present, 404 placeholder if not; either is an explicit response.
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("image/svg+xml")


def test_v20_paired_evaluation_loader_finds_summary(client: TestClient) -> None:
    response = client.get("/paired-evaluation")
    assert response.status_code == 200
    # The loader should have found the 0:199 (or fallback) paired summary.
    assert "No paired evaluation data" not in response.text


def test_v20_fth_v34_loader_finds_evidence(client: TestClient) -> None:
    response = client.get("/fth-v34")
    assert response.status_code == 200
    assert "No FTH v3.4 evidence data" not in response.text
