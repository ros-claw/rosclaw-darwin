"""Statistical utilities for normalized LeRobot evaluation results.

These helpers operate on Darwin-normalized episode/task structures and do not
import LeRobot or PyTorch.
"""

from __future__ import annotations

import math
from typing import Any


def _success_value(episode: Any) -> bool:
    """Return the boolean success flag for an episode object or mapping."""
    if isinstance(episode, dict):
        value = episode.get("success")
    else:
        value = getattr(episode, "success", None)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return bool(value)


def _reward_value(episode: Any, name: str) -> float | None:
    """Return a reward metric from an episode object or mapping."""
    if isinstance(episode, dict):
        value = episode.get(name)
    else:
        value = getattr(episode, name, None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _z_alpha(alpha: float) -> float:
    """Two-sided normal quantile for confidence level ``1 - alpha``.

    Uses a rational approximation (Abramowitz & Stegun 26.2.17).
    """
    p = 1 - alpha / 2
    if p <= 0 or p >= 1:
        return 1.96
    if p < 0.5:
        p = 1 - p
    t = math.sqrt(-2 * math.log(1 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    num = c0 + c1 * t + c2 * t * t
    denom = 1 + d1 * t + d2 * t * t + d3 * t * t * t
    return t - num / denom


def wilson_ci(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Args:
        successes: Number of successful trials.
        n: Total number of trials.
        confidence: Confidence level (e.g. 0.95 for 95%).

    Returns:
        ``(lower, upper)`` bounds clipped to ``[0.0, 1.0]``.  ``n <= 0`` yields
        ``(0.0, 0.0)``.
    """
    if n <= 0:
        return 0.0, 0.0
    successes = int(successes)
    if successes <= 0:
        return 0.0, 0.0
    if successes >= n:
        return 1.0, 1.0

    alpha = 1 - confidence
    z = _z_alpha(alpha)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half_width = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def micro_success_rate(episodes: list[Any]) -> float:
    """Pooled success rate across all episodes."""
    if not episodes:
        return 0.0
    successes = sum(1 for ep in episodes if _success_value(ep))
    return successes / len(episodes)


def macro_task_success_rate(tasks: list[Any]) -> float:
    """Mean per-task success rate, weighting each task equally.

    Tasks may be supplied as mappings/objects with either:

    * ``num_successes`` and ``num_episodes``
    * ``success_rate``
    * an iterable of episodes
    """
    if not tasks:
        return 0.0

    rates: list[float] = []
    for task in tasks:
        if isinstance(task, dict):
            num_successes = task.get("num_successes")
            num_episodes = task.get("num_episodes")
            rate = task.get("success_rate")
            episodes = task.get("episodes", [])
        else:
            num_successes = getattr(task, "num_successes", None)
            num_episodes = getattr(task, "num_episodes", None)
            rate = getattr(task, "success_rate", None)
            episodes = getattr(task, "episodes", [])

        if rate is not None:
            rates.append(float(rate))
        elif num_successes is not None and num_episodes:
            rates.append(max(0, min(int(num_successes), int(num_episodes))) / int(num_episodes))
        elif episodes:
            rates.append(micro_success_rate(list(episodes)))

    if not rates:
        return 0.0
    return sum(rates) / len(rates)


def compute_task_statistics(task_episodes: dict[str, list[Any]]) -> dict[str, dict[str, Any]]:
    """Compute per-task summary statistics from grouped episodes.

    Args:
        task_episodes: Mapping from task identifier to a list of episode
            objects/mappings.

    Returns:
        Mapping from task identifier to a dict containing ``success_rate``,
        ``success_ci_low``, ``success_ci_high``, ``avg_sum_reward``,
        ``avg_max_reward``, and ``eval_seconds``.
    """
    result: dict[str, dict[str, Any]] = {}
    for task_id, episodes in task_episodes.items():
        n = len(episodes)
        successes = sum(1 for ep in episodes if _success_value(ep))
        ci_low, ci_high = wilson_ci(successes, n)

        sum_rewards = [v for ep in episodes if (v := _reward_value(ep, "sum_reward")) is not None]
        max_rewards = [v for ep in episodes if (v := _reward_value(ep, "max_reward")) is not None]
        episode_seconds = [
            v for ep in episodes if (v := _reward_value(ep, "episode_seconds")) is not None
        ]

        result[task_id] = {
            "success_rate": successes / n if n else 0.0,
            "success_ci_low": ci_low,
            "success_ci_high": ci_high,
            "avg_sum_reward": sum(sum_rewards) / len(sum_rewards) if sum_rewards else None,
            "std_sum_reward": _std(sum_rewards),
            "avg_max_reward": sum(max_rewards) / len(max_rewards) if max_rewards else None,
            "std_max_reward": _std(max_rewards),
            "eval_seconds": sum(episode_seconds) if episode_seconds else None,
        }
    return result


def _std(values: list[float]) -> float | None:
    """Population standard deviation of a list of floats."""
    if not values:
        return None
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    return math.sqrt(variance)


def reward_mean_std(episodes: list[Any], name: str) -> tuple[float | None, float | None]:
    """Return the mean and population standard deviation of reward ``name``."""
    values = [v for ep in episodes if (v := _reward_value(ep, name)) is not None]
    if not values:
        return None, None
    mean = sum(values) / len(values)
    return mean, _std(values)


def smoke_sample_warning(n_episodes: int) -> str | None:
    """Return a warning label for very small episode samples."""
    if n_episodes < 10:
        return "smoke_sample_only"
    return None
