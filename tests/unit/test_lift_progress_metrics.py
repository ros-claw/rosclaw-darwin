"""Tests for lift_object progress metrics and failure-type inference."""

from __future__ import annotations

import pytest

from rosclaw_darwin.evaluation.progress_metrics import (
    compute_episode_metrics,
    compute_lift_progress,
    infer_failure_type,
    summarize_episodes,
)


def _trace_moving_closer() -> list[dict]:
    """EEF moves from far above to directly above the object."""
    trace = []
    for i in range(10):
        trace.append({
            "eef_x": 0.08 + 0.04 * i,
            "eef_y": -0.05,
            "eef_z": 0.84 - 0.03 * i,
            "object_x": 0.5,
            "object_y": 0.0,
            "object_z": 0.055,
            "target_x": 0.5,
            "target_y": 0.0,
            "target_z": 0.3,
            "action_norm": 0.5,
        })
    return trace


def test_progress_increases_when_eef_moves_closer():
    trace = _trace_moving_closer()
    metrics = compute_episode_metrics(trace)
    assert metrics["progress"] > 0.0
    assert metrics["eef_to_object_distance_initial"] > metrics["eef_to_object_distance_min"]


def test_failure_type_target_not_reached():
    trace = _trace_moving_closer()
    metrics = compute_episode_metrics(trace, grasp_dist_threshold=0.001)
    assert metrics["failure_type"] == "target_not_reached"


def test_failure_type_object_not_lifted():
    trace = _trace_moving_closer()
    # Place eef right on top of the object so it "reaches" it, but object does not move.
    for step in trace:
        step["eef_x"] = step["object_x"]
        step["eef_y"] = step["object_y"]
        step["eef_z"] = step["object_z"] + 0.01
    metrics = compute_episode_metrics(trace)
    assert metrics["failure_type"] == "object_not_lifted"


def test_failure_type_policy_noop():
    trace = [
        {
            "eef_x": 0.08,
            "eef_y": -0.05,
            "eef_z": 0.84,
            "object_x": 0.5,
            "object_y": 0.0,
            "object_z": 0.055,
            "target_x": 0.5,
            "target_y": 0.0,
            "target_z": 0.3,
            "action_norm": 0.0,
        }
        for _ in range(10)
    ]
    metrics = compute_episode_metrics(trace)
    assert metrics["failure_type"] == "policy_noop"
    assert metrics["nonzero_action_rate"] == 0.0


def test_success_when_object_reaches_target():
    trace = []
    for i in range(5):
        trace.append({
            "eef_x": 0.5,
            "eef_y": 0.0,
            "eef_z": 0.3,
            "object_x": 0.5,
            "object_y": 0.0,
            "object_z": 0.055 if i == 0 else 0.3,
            "target_x": 0.5,
            "target_y": 0.0,
            "target_z": 0.3,
            "action_norm": 0.2,
        })
    metrics = compute_episode_metrics(trace)
    assert metrics["success"] is True
    assert metrics["failure_type"] == "unknown_failure"
    assert metrics["progress"] == pytest.approx(1.0, abs=0.05)


def test_summarize_episodes_aggregates_progress():
    trace1 = _trace_moving_closer()
    trace2 = _trace_moving_closer()
    ep1 = compute_episode_metrics(trace1)
    ep2 = compute_episode_metrics(trace2)
    summary = summarize_episodes([ep1, ep2])
    assert summary["num_episodes"] == 2
    assert 0.0 < summary["progress_mean"] <= 1.0
    assert "target_not_reached" in summary["failure_counts"]


def test_oracle_summary_clears_skill_metrics():
    ep = compute_episode_metrics(_trace_moving_closer())
    summary = summarize_episodes([ep], is_oracle=True)
    assert summary["leaderboard_excluded"] is True
    assert summary["can_claim_capability"] is False
    assert summary["skill_discovery_rate"] is None


def test_lift_progress_formula():
    progress = compute_lift_progress(
        eef_to_object_initial=0.5,
        eef_to_object_min=0.1,
        object_height_initial=0.055,
        object_height_max=0.155,
        object_to_target_initial=0.3,
        object_to_target_final=0.05,
        required_lift_height=0.25,
    )
    # approach=0.8, lift=0.4, target=0.833 -> weighted
    expected = 0.5 * 0.8 + 0.3 * 0.4 + 0.2 * (0.25 / 0.3)
    assert progress == pytest.approx(expected, abs=1e-4)


def test_infer_failure_type_ordering():
    assert infer_failure_type(False, False, False, 0.5) == "target_not_reached"
    assert infer_failure_type(True, False, False, 0.5) == "object_not_lifted"
    assert infer_failure_type(True, True, False, 0.5) == "target_not_reached_after_lift"
    assert infer_failure_type(False, False, False, 0.0) == "policy_noop"
    assert infer_failure_type(True, True, True, 0.5) == "unknown_failure"
