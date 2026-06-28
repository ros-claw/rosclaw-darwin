"""Unit tests for the dashboard SVG chart generator."""

from __future__ import annotations

import pytest

from rosclaw_darwin.dashboard.charts import (
    plot_ablations,
    plot_failure_signature_distribution,
    plot_large_yaw_intervention,
    plot_lift_progress,
    plot_transfer_matrix,
)


def _make_run(episodes: list[dict]) -> dict:
    return {
        "run_id": "run_001",
        "task_id": "darwin_mvp_03_lift_object",
        "policy_id": "heuristic_servo_lift",
        "success_rate": 0.5,
        "progress_mean": 0.75,
        "num_episodes": len(episodes),
        "episode_metrics": episodes,
    }


def test_plot_lift_progress_returns_svg() -> None:
    episodes = [
        {"episode": 0, "success": True, "progress": 0.9, "object_height_delta": 0.2, "eef_to_object_distance_min": 0.01},
        {"episode": 1, "success": False, "progress": 0.3, "object_height_delta": 0.05, "eef_to_object_distance_min": 0.1},
    ]
    svg = plot_lift_progress(_make_run(episodes))
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>\n")
    assert "darwin_mvp_03_lift_object" in svg


def test_plot_lift_progress_empty_data() -> None:
    svg = plot_lift_progress(_make_run([]))
    assert "No episode data" in svg


def test_plot_ablations_returns_svg() -> None:
    ablations = [
        {
            "task_id": "lift_object",
            "policy_id": "heuristic_servo_lift",
            "without_hints_sr": 0.3,
            "manual_hints_sr": 0.35,
            "with_auto_hints_sr": 0.4,
            "without_hints_progress": 0.7,
            "manual_hints_progress": 0.75,
            "with_auto_hints_progress": 0.8,
            "skill_transfer_gain": 0.1,
            "auto_hint_names": ["grasp_adjust"],
        }
    ]
    svg = plot_ablations(ablations)
    assert svg.startswith("<svg")
    assert "lift_object" in svg


def test_plot_failure_signature_distribution_returns_svg() -> None:
    runs = [{"failure_counts": {"target_not_reached_after_lift": 5, "object_not_lifted": 2}}]
    svg = plot_failure_signature_distribution(runs)
    assert svg.startswith("<svg")
    assert "target_not_reached_after_lift" in svg


def test_plot_transfer_matrix_returns_svg() -> None:
    ablations = [
        {"task_id": "lift_object", "skill_transfer_gain": 0.1},
        {"task_id": "pick_object", "skill_transfer_gain": -0.05},
    ]
    svg = plot_transfer_matrix(ablations)
    assert svg.startswith("<svg")
    assert "lift_object" in svg
    assert "pick_object" in svg


def test_plot_large_yaw_intervention_returns_svg() -> None:
    per_condition = {
        "baseline__yaw_1.5708": {
            "condition": "baseline",
            "target_yaw": 1.5708,
            "orientation_achieved_rate": 0.1,
        },
        "grasp_at_target_yaw__yaw_1.5708": {
            "condition": "grasp_at_target_yaw",
            "target_yaw": 1.5708,
            "orientation_achieved_rate": 0.1,
        },
    }
    svg = plot_large_yaw_intervention(per_condition)
    assert svg.startswith("<svg")
    assert "baseline" in svg
    assert svg.endswith("</svg>\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
