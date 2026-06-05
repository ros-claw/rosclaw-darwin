"""Metrics bridge: normalize Arena metrics to Darwin format."""

from __future__ import annotations

from typing import Any


class MetricsBridge:
    """Normalize metrics from Arena runners to Darwin EvaluationResult."""

    ARENA_TO_DARWIN: dict[str, str] = {
        "success_rate": "success_rate",
        "avg_episode_length": "completion_time_mean",
        "collision_count": "collision_count_mean",
        "num_episodes": "num_episodes",
    }

    @classmethod
    def normalize(cls, arena_metrics: dict[str, Any]) -> dict[str, float]:
        result: dict[str, float] = {}
        for arena_key, darwin_key in cls.ARENA_TO_DARWIN.items():
            if arena_key in arena_metrics:
                try:
                    result[darwin_key] = float(arena_metrics[arena_key])
                except (ValueError, TypeError):
                    continue
        return result
