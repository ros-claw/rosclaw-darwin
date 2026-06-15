"""Unit tests for grasp stability metrics."""

from __future__ import annotations

import pytest

from rosclaw_darwin.evaluation.grasp_metrics import (
    infer_grasp_stability,
    summarize_grasp_stability,
)


def _make_step(eef, obj, gripper=None, phase="LIFT"):
    return {
        "eef_x": eef[0],
        "eef_y": eef[1],
        "eef_z": eef[2],
        "object_x": obj[0],
        "object_y": obj[1],
        "object_z": obj[2],
        "gripper_pos": gripper,
        "phase": phase,
    }


def test_empty_trace_returns_zero_score():
    result = infer_grasp_stability([])
    assert result["object_lifted"] is False
    assert result["grasp_stability_score"] == 0.0


def test_lifted_and_held_is_stable():
    trace = [
        _make_step([0.0, 0.0, 0.10], [0.0, 0.0, 0.05]),
        _make_step([0.0, 0.0, 0.15], [0.0, 0.0, 0.10]),
        _make_step([0.0, 0.0, 0.20], [0.0, 0.0, 0.15]),
        _make_step([0.0, 0.0, 0.20], [0.0, 0.0, 0.15]),
    ]
    result = infer_grasp_stability(trace, lift_threshold=0.05)
    assert result["object_lifted"] is True
    assert result["drop_detected"] is False
    assert result["object_follows_eef"] is True
    assert result["grasp_stability_score"] == pytest.approx(1.0)


def test_lifted_then_dropped_detected():
    trace = [
        _make_step([0.0, 0.0, 0.10], [0.0, 0.0, 0.05]),
        _make_step([0.0, 0.0, 0.30], [0.0, 0.0, 0.20]),
        _make_step([0.0, 0.0, 0.30], [0.0, 0.0, 0.05]),
    ]
    result = infer_grasp_stability(trace, lift_threshold=0.05, drop_threshold=0.05)
    assert result["object_lifted"] is True
    assert result["drop_detected"] is True
    assert result["object_height_drop_after_peak"] == pytest.approx(0.15)
    assert result["grasp_stability_score"] == pytest.approx(0.4)


def test_object_not_following_eef():
    trace = [
        _make_step([0.0, 0.0, 0.10], [0.0, 0.0, 0.05]),
        _make_step([0.0, 0.0, 0.30], [0.0, 0.0, 0.20]),
        _make_step([0.0, 0.0, 0.25], [0.5, 0.0, 0.20]),
    ]
    result = infer_grasp_stability(trace, lift_threshold=0.05)
    assert result["object_lifted"] is True
    assert result["object_follows_eef"] is False


def test_summarize_across_episodes():
    stable = [
        _make_step([0.0, 0.0, 0.10], [0.0, 0.0, 0.05]),
        _make_step([0.0, 0.0, 0.30], [0.0, 0.0, 0.20]),
    ]
    dropped = [
        _make_step([0.0, 0.0, 0.10], [0.0, 0.0, 0.05]),
        _make_step([0.0, 0.0, 0.30], [0.0, 0.0, 0.20]),
        _make_step([0.0, 0.0, 0.30], [0.0, 0.0, 0.05]),
    ]
    summary = summarize_grasp_stability([stable, dropped], lift_threshold=0.05)
    assert summary["summary"]["num_episodes"] == 2
    assert summary["summary"]["object_lifted_rate"] == 1.0
    assert summary["summary"]["drop_detected_rate"] == 0.5
