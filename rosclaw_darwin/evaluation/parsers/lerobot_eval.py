"""Parser for LeRobot ``eval_info.json`` outputs.

LeRobot's ``lerobot-eval`` writes per-run evidence to
``<output_dir>/eval_info.json``. This module turns that official output into a
structured, Darwin-normalized representation while preserving the raw JSON for
auditability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EvalErrorCode(str, Enum):
    """Structured error codes for eval_info parsing failures."""

    eval_info_missing = "eval_info_missing"
    eval_info_invalid_json = "eval_info_invalid_json"
    eval_schema_unsupported = "eval_schema_unsupported"
    episode_count_mismatch = "episode_count_mismatch"
    task_result_missing = "task_result_missing"
    metric_type_invalid = "metric_type_invalid"


class EvalInfoError(Exception):
    """Structured exception raised when parsing fails."""

    def __init__(self, code: EvalErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EpisodeResult:
    """One evaluated episode from ``eval_info.json``."""

    task: str
    episode_index: int
    success: bool
    sum_reward: float
    max_reward: float
    steps: int | None = None
    terminated: bool | None = None
    truncated: bool | None = None
    video_path: str | None = None
    seed: int | None = None
    suite: str | None = None


@dataclass
class TaskResult:
    """Aggregated results for a single benchmark task."""

    task_id: str
    suite: str | None = None
    group: str | None = None
    avg_sum_reward: float | None = None
    avg_max_reward: float | None = None
    pc_success: float | None = None
    success_rate: float | None = None
    eval_s: float | None = None
    eval_ep_s: float | None = None
    episodes: list[EpisodeResult] = field(default_factory=list)


@dataclass
class LerobotEvalInfo:
    """Structured representation of a LeRobot ``eval_info.json`` file."""

    raw: dict[str, Any] = field(default_factory=dict)
    avg_sum_reward: float | None = None
    avg_max_reward: float | None = None
    pc_success: float | None = None
    success_rate: float | None = None
    eval_s: float | None = None
    eval_ep_s: float | None = None
    tasks: dict[str, TaskResult] = field(default_factory=dict)
    episodes: list[EpisodeResult] = field(default_factory=list)


def _as_float(value: Any, name: str) -> float:
    """Coerce a metric to ``float``, raising a structured error on failure."""
    if value is None:
        raise EvalInfoError(
            EvalErrorCode.metric_type_invalid,
            f"Metric '{name}' is missing (None).",
        )
    if isinstance(value, bool):
        raise EvalInfoError(
            EvalErrorCode.metric_type_invalid,
            f"Metric '{name}' has boolean value; expected numeric.",
        )
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise EvalInfoError(
            EvalErrorCode.metric_type_invalid,
            f"Metric '{name}' is not numeric: {value!r}.",
        ) from exc


def _optional_float(value: Any, name: str) -> float | None:
    """Coerce a metric to ``float`` when present, or ``None`` when absent."""
    if value is None:
        return None
    return _as_float(value, name)


def _as_bool(value: Any) -> bool:
    """Coerce a success/termination flag to ``bool``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return bool(value)


def _as_int(value: Any) -> int | None:
    """Coerce an integer field, returning ``None`` when missing or invalid."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_episode(
    item: Any,
    default_task: str | None,
    suite: str | None = None,
) -> EpisodeResult:
    """Parse a single per-episode entry."""
    if not isinstance(item, dict):
        raise EvalInfoError(
            EvalErrorCode.eval_schema_unsupported,
            f"Episode entry is not an object: {item!r}.",
        )

    task = item.get("task")
    if task is None:
        task = default_task
    if task is None:
        raise EvalInfoError(
            EvalErrorCode.task_result_missing,
            "Episode entry is missing 'task' and no default task is available.",
        )

    return EpisodeResult(
        task=str(task),
        episode_index=_as_int(item.get("episode_index", item.get("episode_ix"))) if ("episode_index" in item or "episode_ix" in item) else 0,
        success=_as_bool(item.get("success")),
        sum_reward=_optional_float(item.get("sum_reward"), "sum_reward") or 0.0,
        max_reward=_optional_float(item.get("max_reward"), "max_reward") or 0.0,
        steps=_as_int(item.get("steps", item.get("episode_steps"))),
        terminated=_as_bool(item.get("terminated")) if "terminated" in item else None,
        truncated=_as_bool(item.get("truncated")) if "truncated" in item else None,
        video_path=(str(v) if (v := item.get("video_path", item.get("video"))) is not None else None),
        seed=_as_int(item.get("seed")) if "seed" in item else None,
        suite=suite,
    )


def _extract_overall(source: dict[str, Any]) -> dict[str, Any]:
    """Return the overall-metric container, whether flat or nested."""
    for key in ("aggregated", "overall"):
        if key in source and isinstance(source[key], dict):
            return source[key]
    return source


def _parse_task_metrics(task_obj: dict[str, Any]) -> dict[str, Any]:
    """Parse aggregate metrics from a task/suite object."""
    # LeRobot 0.3.x stores aggregated metrics under ``aggregated``.
    overall = _extract_overall(task_obj)
    if "aggregated" in task_obj and isinstance(task_obj["aggregated"], dict):
        overall = task_obj["aggregated"]
    metrics: dict[str, Any] = {}
    for key in ("avg_sum_reward", "avg_max_reward", "pc_success", "eval_s", "eval_ep_s"):
        if key in overall:
            metrics[key] = _optional_float(overall[key], key)
    pc_success = metrics.get("pc_success")
    metrics["success_rate"] = pc_success / 100.0 if pc_success is not None else None
    return metrics


def _parse_task(
    task_id: str,
    task_obj: dict[str, Any],
    suite: str | None = None,
    group: str | None = None,
) -> TaskResult:
    """Parse a task container and its episodes."""
    metrics = _parse_task_metrics(task_obj)
    task = TaskResult(
        task_id=task_id,
        suite=suite,
        group=group,
        avg_sum_reward=metrics.get("avg_sum_reward"),
        avg_max_reward=metrics.get("avg_max_reward"),
        pc_success=metrics.get("pc_success"),
        success_rate=metrics.get("success_rate"),
        eval_s=metrics.get("eval_s"),
        eval_ep_s=metrics.get("eval_ep_s"),
    )

    episodes_raw = task_obj.get("episodes")
    if not isinstance(episodes_raw, list):
        episodes_raw = task_obj.get("per_episode")
    if isinstance(episodes_raw, list):
        for item in episodes_raw:
            task.episodes.append(_parse_episode(item, default_task=task_id, suite=task.suite))

    return task


def _parse_tasks(raw: dict[str, Any]) -> dict[str, TaskResult]:
    """Discover task structure inside ``eval_info.json``."""
    tasks: dict[str, TaskResult] = {}

    # Explicit task dictionary.
    tasks_raw = raw.get("tasks")
    if isinstance(tasks_raw, dict):
        for task_id, task_obj in tasks_raw.items():
            if not isinstance(task_obj, dict):
                continue
            tasks[str(task_id)] = _parse_task(str(task_id), task_obj)
        return tasks

    # Suite / group nesting.
    suites_raw = raw.get("suites")
    if isinstance(suites_raw, dict):
        for suite_name, suite_obj in suites_raw.items():
            if not isinstance(suite_obj, dict):
                continue
            groups_raw = suite_obj.get("groups", suite_obj)
            if not isinstance(groups_raw, dict):
                continue
            for group_name, group_obj in groups_raw.items():
                if not isinstance(group_obj, dict):
                    continue
                tasks_in_group = group_obj.get("tasks")
                if isinstance(tasks_in_group, dict):
                    for task_id, task_obj in tasks_in_group.items():
                        if isinstance(task_obj, dict):
                            tasks[str(task_id)] = _parse_task(
                                str(task_id), task_obj, suite=str(suite_name), group=str(group_name)
                            )
        return tasks

    # Single-task fallback.
    default_task = raw.get("task")
    if default_task is None:
        env = raw.get("env")
        if isinstance(env, dict):
            default_task = env.get("task")
    if default_task is None:
        default_task = "default"

    task = _parse_task(str(default_task), raw)
    # LeRobot 0.3.x writes per-episode results under ``per_episode`` instead of
    # ``episodes``.  ``_parse_task`` consumed whichever key was present.
    tasks[str(default_task)] = task
    return tasks


def parse_eval_info(
    output_dir: Path,
    expected_episodes: int | None = None,
) -> LerobotEvalInfo:
    """Parse ``<output_dir>/eval_info.json`` into a structured representation.

    Args:
        output_dir: Directory containing the LeRobot evaluation output.
        expected_episodes: If provided, the parser validates that the number of
            parsed episodes matches this value.

    Returns:
        A ``LerobotEvalInfo`` with raw JSON preserved.

    Raises:
        EvalInfoError: When a structured parsing or validation error occurs.
    """
    path = Path(output_dir) / "eval_info.json"
    if not path.exists():
        raise EvalInfoError(
            EvalErrorCode.eval_info_missing,
            f"eval_info.json not found at {path}.",
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalInfoError(
            EvalErrorCode.eval_info_invalid_json,
            f"eval_info.json is not valid JSON: {exc}.",
        ) from exc

    if not isinstance(raw, dict):
        raise EvalInfoError(
            EvalErrorCode.eval_schema_unsupported,
            "eval_info.json root must be a JSON object.",
        )

    overall = _extract_overall(raw)
    avg_sum_reward = _optional_float(overall.get("avg_sum_reward"), "avg_sum_reward")
    avg_max_reward = _optional_float(overall.get("avg_max_reward"), "avg_max_reward")
    pc_success = _optional_float(overall.get("pc_success"), "pc_success")
    eval_s = _optional_float(overall.get("eval_s"), "eval_s")
    eval_ep_s = _optional_float(overall.get("eval_ep_s"), "eval_ep_s")

    tasks = _parse_tasks(raw)
    episodes: list[EpisodeResult] = []
    for task in tasks.values():
        episodes.extend(task.episodes)

    if expected_episodes is not None and len(episodes) != expected_episodes:
        raise EvalInfoError(
            EvalErrorCode.episode_count_mismatch,
            f"Expected {expected_episodes} episodes, found {len(episodes)}.",
        )

    success_rate = pc_success / 100.0 if pc_success is not None else None

    return LerobotEvalInfo(
        raw=raw,
        avg_sum_reward=avg_sum_reward,
        avg_max_reward=avg_max_reward,
        pc_success=pc_success,
        success_rate=success_rate,
        eval_s=eval_s,
        eval_ep_s=eval_ep_s,
        tasks=tasks,
        episodes=episodes,
    )
