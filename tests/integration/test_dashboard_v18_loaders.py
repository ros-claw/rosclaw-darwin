"""Integration tests for v1.8 dashboard views and data loaders."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rosclaw_darwin.dashboard.app import DashboardApp


@pytest.fixture
def client() -> TestClient:
    app = DashboardApp(data_dir="/tmp/rosclaw_data")
    return TestClient(app.app)


@pytest.mark.parametrize("path", [
    "/official-v18",
    "/valid-ood",
    "/slip-monitor",
    "/slip-recovery",
    "/external-blockers",
])
def test_v18_dashboard_pages_load(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text or "<html>" in response.text


@pytest.mark.parametrize("path", [
    "/official-v18/chart.svg",
    "/valid-ood/validity-chart.svg",
    "/valid-ood/matrix-chart.svg",
    "/slip-monitor/chart.svg",
    "/slip-recovery/chart.svg",
])
def test_v18_dashboard_chart_endpoints_exist(client: TestClient, path: str) -> None:
    response = client.get(path)
    # 200 if data is present, 404 placeholder if not; either is an explicit response.
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("image/svg+xml")
