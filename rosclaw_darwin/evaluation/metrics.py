"""Metrics computation for embodied AI evaluation.

Traditional benchmarks measure Success Rate. Darwin measures
Skill Discovery Rate (SDR), Memory Integration Efficiency (MIE),
and Swarm Synergy Index (SSI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class EvaluationMetrics:
    """Standard + Evolutionary metrics for a single evaluation run."""

    # --- Traditional metrics ---
    success: bool = False
    completion_time: float = 0.0
    path_length: float = 0.0
    collision_count: int = 0
    step_count: int = 0

    # --- Evolutionary metrics (Phase 2+) ---
    skill_discovery_rate: float = 0.0  # SDR: new skills per episode
    memory_integration_efficiency: float = 0.0  # MIE: errors avoided on retry
    swarm_synergy_index: float = 0.0  # SSI: multi-agent coordination score
    evolution_delta: float = 0.0  # score_delta between loop1 and loop2

    # --- Raw data for downstream analysis ---
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "completion_time": self.completion_time,
            "path_length": self.path_length,
            "collision_count": self.collision_count,
            "step_count": self.step_count,
            "skill_discovery_rate": self.skill_discovery_rate,
            "memory_integration_efficiency": self.memory_integration_efficiency,
            "swarm_synergy_index": self.swarm_synergy_index,
            "evolution_delta": self.evolution_delta,
            "info": self.info,
        }


def compute_metrics(
    trajectory: list[dict[str, Any]],
    success: bool = False,
    time_limit: float = 120.0,
) -> EvaluationMetrics:
    """Compute metrics from a recorded trajectory.

    Args:
        trajectory: List of step dicts, each with keys like
                    'obs', 'action', 'reward', 'info'.
        success:    Whether the task was completed successfully.
        time_limit: Maximum allowed time in seconds.
    """
    step_count = len(trajectory)
    total_reward = 0.0
    collision_count = 0
    positions: list[tuple[float, ...]] = []

    for step in trajectory:
        reward = step.get("reward", 0.0)
        total_reward += reward
        info = step.get("info", {})
        if info.get("collision", False):
            collision_count += 1
        if "position" in info:
            positions.append(tuple(info["position"]))

    path_length = 0.0
    if len(positions) > 1:
        arr = np.array(positions)
        diffs = np.diff(arr, axis=0)
        path_length = float(np.sum(np.linalg.norm(diffs, axis=1)))

    completion_time = step_count * 0.05  # Assume 50ms per step default

    # Path efficiency = straight_line / actual_path (0 if no positions)
    path_efficiency = 0.0
    if len(positions) > 1 and path_length > 0:
        straight_line = float(np.linalg.norm(np.array(positions[-1]) - np.array(positions[0])))
        path_efficiency = min(straight_line / path_length, 1.0)

    return EvaluationMetrics(
        success=success,
        completion_time=completion_time,
        path_length=path_length,
        collision_count=collision_count,
        step_count=step_count,
        trajectory=trajectory,
        info={
            "total_reward": total_reward,
            "path_efficiency": path_efficiency,
            "time_efficiency": min(completion_time / time_limit, 1.0) if time_limit > 0 else 0.0,
        },
    )
