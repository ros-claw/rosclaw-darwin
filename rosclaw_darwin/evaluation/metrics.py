"""Metrics computation for embodied AI evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np


def compute_basic_metrics(episodes: list[dict[str, Any]]) -> dict[str, float]:
    """Compute basic metrics from a list of episode results."""
    if not episodes:
        return {}
    successes = [e["success"] for e in episodes]
    collisions = [e.get("collisions", 0) for e in episodes]
    times = [e.get("time", 0.0) for e in episodes]

    success_times = [t for s, t in zip(successes, times) if s]
    success_collisions = [c for s, c in zip(successes, collisions) if s]

    return {
        "success_rate": float(np.mean(successes)),
        "completion_time_mean": float(np.mean(success_times)) if success_times else 0.0,
        "completion_time_std": float(np.std(success_times)) if success_times else 0.0,
        "episode_time_mean": float(np.mean(times)),
        "episode_time_std": float(np.std(times)),
        "collision_count_mean": float(np.mean(success_collisions)) if success_collisions else float(np.mean(collisions)),
        "collision_count_overall_mean": float(np.mean(collisions)),
        "progress_mean": float(np.mean(successes)),  # proxy
        "path_efficiency": 0.0,  # placeholder
        "energy_cost": 0.0,  # placeholder
        "num_episodes": len(episodes),
        "num_success": int(sum(successes)),
    }


def compute_evolution_metrics(
    loop1: dict[str, float],
    loop2: dict[str, float],
) -> dict[str, float]:
    """Compute evolution metrics comparing two evaluation loops."""
    delta_success_rate = loop2.get("success_rate", 0.0) - loop1.get("success_rate", 0.0)

    same_failure_loop1 = loop1.get("num_failures", 0)
    same_failure_loop2 = loop2.get("num_failures", 0)

    if same_failure_loop1 == 0:
        mie_raw = None
        mie_score = 0.0
        mie_available = False
    else:
        mie_raw = 1.0 - same_failure_loop2 / same_failure_loop1
        mie_score = max(0.0, min(1.0, mie_raw))
        mie_available = True

    skill_discovery_rate = loop2.get("skill_discovery_rate", 0.0)
    robustness_loop1 = loop1.get("success_rate", 0.0)
    robustness_loop2 = loop2.get("success_rate", 0.0)
    robustness_gain = robustness_loop2 - robustness_loop1

    completion_time_improvement = 0.0
    if loop1.get("completion_time_mean", 0.0) > 0:
        completion_time_improvement = (
            loop1["completion_time_mean"] - loop2.get("completion_time_mean", 0.0)
        ) / loop1["completion_time_mean"]

    evolution_score = (
        0.4 * delta_success_rate
        + 0.2 * mie_score
        + 0.2 * skill_discovery_rate
        + 0.1 * completion_time_improvement
        + 0.1 * robustness_gain
    )

    return {
        "delta_success_rate": delta_success_rate,
        "memory_integration_efficiency_raw": mie_raw,
        "memory_integration_efficiency_score": mie_score,
        "memory_integration_efficiency_available": mie_available,
        "skill_discovery_rate": skill_discovery_rate,
        "robustness_gain": robustness_gain,
        "completion_time_improvement": completion_time_improvement,
        "evolution_score": evolution_score,
    }
