"""Tests for metrics."""

import pytest

from rosclaw_darwin.evaluation.metrics import compute_basic_metrics, compute_evolution_metrics


class TestMetrics:
    def test_basic_metrics(self):
        episodes = [
            {"success": True, "steps": 100, "collisions": 0, "time": 5.0},
            {"success": False, "steps": 200, "collisions": 3, "time": 10.0},
        ]
        m = compute_basic_metrics(episodes)
        assert m["success_rate"] == 0.5
        assert m["num_episodes"] == 2

    def test_evolution_metrics_improvement(self):
        loop1 = {"success_rate": 0.2, "num_failures": 8, "completion_time_mean": 100.0}
        loop2 = {"success_rate": 0.6, "num_failures": 4, "completion_time_mean": 80.0}
        evo = compute_evolution_metrics(loop1, loop2)
        assert evo["delta_success_rate"] == pytest.approx(0.4)
        assert evo["evolution_score"] > 0
