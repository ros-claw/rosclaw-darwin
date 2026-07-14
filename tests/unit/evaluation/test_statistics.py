"""Unit tests for evaluation/statistics.py."""

from __future__ import annotations

import math

import pytest

from rosclaw_darwin.evaluation.statistics import (
    compute_task_statistics,
    macro_task_success_rate,
    micro_success_rate,
    reward_mean_std,
    smoke_sample_warning,
    wilson_ci,
)


def test_wilson_ci_bounds() -> None:
    """Wilson CI stays inside [0, 1] and straddles the observed proportion."""
    lower, upper = wilson_ci(5, 10)
    assert 0.0 <= lower <= upper <= 1.0
    assert lower < 0.5 < upper


def test_wilson_ci_full_success() -> None:
    """All-success yields an upper bound of 1.0."""
    lower, upper = wilson_ci(10, 10)
    assert lower > 0.5
    assert upper == 1.0


def test_wilson_ci_empty() -> None:
    """Zero trials yields a degenerate (0, 0) interval."""
    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_ci_clamps_out_of_range_successes() -> None:
    """Out-of-range success counts are clamped before computing the interval."""
    lower, upper = wilson_ci(15, 10)
    assert upper == 1.0
    assert lower > 0.5


def test_micro_success_rate() -> None:
    """Micro rate pools all episodes."""
    episodes = [
        {"success": True},
        {"success": False},
        {"success": True},
    ]
    assert micro_success_rate(episodes) == pytest.approx(2 / 3)


def test_micro_success_rate_empty() -> None:
    """Empty episode list returns 0.0."""
    assert micro_success_rate([]) == 0.0


def test_macro_task_success_rate() -> None:
    """Macro rate averages per-task rates with equal weight."""
    tasks = [
        {"num_successes": 1, "num_episodes": 1},
        {"num_successes": 0, "num_episodes": 2},
    ]
    # (1.0 + 0.0) / 2, not (1 + 0) / 3.
    assert macro_task_success_rate(tasks) == pytest.approx(0.5)


def test_macro_task_success_rate_from_rate() -> None:
    """Tasks can supply a pre-computed success_rate."""
    tasks = [{"success_rate": 0.8}, {"success_rate": 0.4}]
    assert macro_task_success_rate(tasks) == pytest.approx(0.6)


def test_macro_task_success_rate_from_episodes() -> None:
    """Tasks can supply episode lists."""
    tasks = [
        {"episodes": [{"success": True}, {"success": False}]},
        {"episodes": [{"success": True}, {"success": True}]},
    ]
    assert macro_task_success_rate(tasks) == pytest.approx(0.75)


def test_macro_task_success_rate_empty() -> None:
    """Empty task list returns 0.0."""
    assert macro_task_success_rate([]) == 0.0


def test_compute_task_statistics() -> None:
    """Per-task statistics include success rate, Wilson CI, and reward means."""
    task_episodes = {
        "task_a": [
            {"success": True, "sum_reward": 0.8, "max_reward": 1.0, "episode_seconds": 5.0},
            {"success": False, "sum_reward": 0.4, "max_reward": 0.5, "episode_seconds": 4.0},
        ],
    }
    stats = compute_task_statistics(task_episodes)["task_a"]
    assert stats["success_rate"] == pytest.approx(0.5)
    assert 0.0 <= stats["success_ci_low"] <= stats["success_ci_high"] <= 1.0
    assert stats["avg_sum_reward"] == pytest.approx(0.6)
    assert stats["avg_max_reward"] == pytest.approx(0.75)
    assert stats["eval_seconds"] == pytest.approx(9.0)


def test_compute_task_statistics_missing_rewards() -> None:
    """Missing reward/seconds fields are reported as None, not guessed."""
    task_episodes = {
        "task_a": [{"success": True}, {"success": False}],
    }
    stats = compute_task_statistics(task_episodes)["task_a"]
    assert math.isfinite(stats["success_rate"])
    assert stats["avg_sum_reward"] is None
    assert stats["avg_max_reward"] is None
    assert stats["eval_seconds"] is None


def test_compute_task_statistics_reward_std() -> None:
    """Reward standard deviations are included in per-task statistics."""
    task_episodes = {
        "task_a": [
            {"success": True, "sum_reward": 0.8, "max_reward": 1.0},
            {"success": False, "sum_reward": 0.4, "max_reward": 0.5},
            {"success": True, "sum_reward": 0.6, "max_reward": 0.8},
        ],
    }
    stats = compute_task_statistics(task_episodes)["task_a"]
    assert stats["avg_sum_reward"] == pytest.approx(0.6)
    assert stats["std_sum_reward"] == pytest.approx(0.1632993161855452)
    assert stats["avg_max_reward"] == pytest.approx(0.7666666666666666)
    assert stats["std_max_reward"] is not None
    assert stats["std_sum_reward"] >= 0


def test_reward_mean_std_helper() -> None:
    """reward_mean_std returns the mean and population std of a reward field."""
    episodes = [
        {"sum_reward": 1.0},
        {"sum_reward": 3.0},
        {"sum_reward": 5.0},
    ]
    mean, std = reward_mean_std(episodes, "sum_reward")
    assert mean == pytest.approx(3.0)
    assert std == pytest.approx(1.632993161855452)


def test_reward_mean_std_empty() -> None:
    """Empty episode list yields None mean and std."""
    mean, std = reward_mean_std([], "sum_reward")
    assert mean is None
    assert std is None


def test_smoke_sample_warning() -> None:
    """Small episode counts are flagged as smoke-only."""
    assert smoke_sample_warning(2) == "smoke_sample_only"
    assert smoke_sample_warning(9) == "smoke_sample_only"
    assert smoke_sample_warning(10) is None
    assert smoke_sample_warning(50) is None
