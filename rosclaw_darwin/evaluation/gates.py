"""Validity and performance gates for Darwin evaluation results.

Gates are intentionally separated so that a failed performance gate does not
invalidate the run evidence, and a failed validity gate does not get misreported
as poor policy performance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from rosclaw_darwin.evaluation.parsers.lerobot_eval import LerobotEvalInfo
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evaluation.spec import EvaluationSpec


@dataclass
class ValidityGate:
    """Result of a validity check on a raw evaluation run."""

    status: str  # "passed" or "failed"
    checks: dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceGate:
    """Result of a performance threshold check on a normalized result."""

    status: str  # "passed" or "failed"
    reason: str | None = None


def _get_exit_code(raw_run: Any) -> int | None:
    if isinstance(raw_run, dict):
        return raw_run.get("exit_code")
    return getattr(raw_run, "exit_code", None)


def _is_nan(value: Any) -> bool:
    """Return True when ``value`` is a float NaN."""
    try:
        return isinstance(value, float) and math.isnan(value)
    except TypeError:
        return False


def check_validity(
    raw_run: Any,
    parsed_info: LerobotEvalInfo | None,
    spec: EvaluationSpec,
) -> ValidityGate:
    """Check whether a raw run produced trustworthy evidence.

    Validates process exit code, eval_info presence/parsability, expected
    episode count, and primary-metric finiteness.
    """
    checks: dict[str, Any] = {}
    passed = True

    # 1. Process exit code.
    exit_code = _get_exit_code(raw_run)
    exit_ok = exit_code == 0
    checks["process_exit_code"] = {
        "expected": 0,
        "actual": exit_code,
        "passed": exit_ok,
    }
    passed = passed and exit_ok

    # 2. eval_info exists and parsed.
    eval_info_ok = parsed_info is not None and bool(parsed_info.raw)
    checks["eval_info_parsed"] = {
        "passed": eval_info_ok,
    }
    passed = passed and eval_info_ok

    # 3. Expected episode count.
    episode_count_ok = True
    if spec.validity_gates.require_expected_episode_count:
        expected = spec.evaluation.n_episodes
        actual = len(parsed_info.episodes) if parsed_info else 0
        episode_count_ok = actual == expected
        checks["expected_episode_count"] = {
            "expected": expected,
            "actual": actual,
            "passed": episode_count_ok,
        }
    else:
        checks["expected_episode_count"] = {"passed": None}
    passed = passed and episode_count_ok

    # 4. Primary metric is not NaN.
    primary_metric_ok = True
    if not spec.validity_gates.allow_nan_primary_metric:
        primary_metric = getattr(spec, "primary_metric", None) or "success_rate"
        rate: Any = None
        if parsed_info is not None:
            rate = getattr(parsed_info, primary_metric, None)
            if rate is None and primary_metric == "success_rate":
                rate = parsed_info.success_rate
        primary_metric_ok = rate is not None and not _is_nan(rate)
        checks["primary_metric_finite"] = {
            "metric": primary_metric,
            "value": rate,
            "passed": primary_metric_ok,
        }
    else:
        checks["primary_metric_finite"] = {"passed": None}
    passed = passed and primary_metric_ok

    return ValidityGate(status="passed" if passed else "failed", checks=checks)


def check_performance(
    result: EvaluationResult,
    spec: EvaluationSpec,
) -> PerformanceGate:
    """Check whether a normalized result meets configured performance thresholds."""
    metric_name = getattr(result, "primary_metric", None) or "success_rate"
    success_rate: float | None = result.metrics.get(metric_name)

    min_success_rate = spec.performance_gates.minimum_success_rate
    if min_success_rate is not None:
        if success_rate is None or _is_nan(success_rate) or success_rate < min_success_rate:
            return PerformanceGate(
                status="failed",
                reason=(
                    f"{metric_name}={success_rate} is below "
                    f"minimum_success_rate={min_success_rate}"
                ),
            )

    min_macro = getattr(spec.performance_gates, "minimum_macro_task_success_rate", None)
    if min_macro is not None:
        macro_rate: float | None = result.metrics.get("macro_task_success_rate")
        if macro_rate is None or _is_nan(macro_rate) or macro_rate < min_macro:
            return PerformanceGate(
                status="failed",
                reason=(
                    f"macro_task_success_rate={macro_rate} is below "
                    f"minimum_macro_task_success_rate={min_macro}"
                ),
            )

    return PerformanceGate(status="passed", reason=None)
