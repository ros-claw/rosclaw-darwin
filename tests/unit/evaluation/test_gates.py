"""Unit tests for evaluation validity and performance gates."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from rosclaw_darwin.evaluation.gates import (
    PerformanceGate,
    ValidityGate,
    check_performance,
    check_validity,
)
from rosclaw_darwin.evaluation.parsers.lerobot_eval import EvalInfoError, parse_eval_info
from rosclaw_darwin.evaluation.result_v2 import EvaluationResultV2
from rosclaw_darwin.evaluation.spec import EvaluationSpec


@pytest.fixture
def valid_eval_dir(tmp_path: Path) -> Path:
    """Two-episode single-task eval_info.json."""
    data = {
        "avg_sum_reward": 0.75,
        "avg_max_reward": 0.9,
        "pc_success": 50.0,
        "eval_s": 12.5,
        "eval_ep_s": 6.25,
        "task": "pusht_default",
        "episodes": [
            {
                "task": "pusht_default",
                "episode_index": 0,
                "success": True,
                "sum_reward": 0.8,
                "max_reward": 1.0,
                "steps": 200,
                "terminated": True,
                "truncated": False,
            },
            {
                "task": "pusht_default",
                "episode_index": 1,
                "success": False,
                "sum_reward": 0.7,
                "max_reward": 0.8,
                "steps": 180,
                "terminated": False,
                "truncated": True,
            },
        ],
    }
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    (output_dir / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")
    return output_dir


@pytest.fixture
def spec() -> EvaluationSpec:
    """Default two-episode evaluation spec."""
    return EvaluationSpec(
        id="pusht_smoke",
        backend="lerobot_eval",
        runtime="lerobot_default",
        policy={"path": "lerobot/diffusion_pusht"},
        environment={"type": "pusht"},
        evaluation={"n_episodes": 2},
        output={"root": "data/eval_runs"},
    )


def test_validity_gate_passes(valid_eval_dir: Path, spec: EvaluationSpec) -> None:
    """A clean run passes all validity checks."""
    raw_run = SimpleNamespace(exit_code=0)
    parsed_info = parse_eval_info(valid_eval_dir)

    gate = check_validity(raw_run, parsed_info, spec)

    assert isinstance(gate, ValidityGate)
    assert gate.status == "passed"
    assert gate.checks["process_exit_code"]["passed"] is True
    assert gate.checks["eval_info_parsed"]["passed"] is True
    assert gate.checks["expected_episode_count"]["passed"] is True
    assert gate.checks["primary_metric_finite"]["passed"] is True


def test_validity_gate_fails_bad_exit_code(valid_eval_dir: Path, spec: EvaluationSpec) -> None:
    """A non-zero exit code fails validity."""
    raw_run = SimpleNamespace(exit_code=1)
    parsed_info = parse_eval_info(valid_eval_dir)

    gate = check_validity(raw_run, parsed_info, spec)

    assert gate.status == "failed"
    assert gate.checks["process_exit_code"]["passed"] is False


def test_validity_gate_fails_episode_mismatch(valid_eval_dir: Path, spec: EvaluationSpec) -> None:
    """Episode count mismatch fails validity."""
    raw_run = SimpleNamespace(exit_code=0)
    parsed_info = parse_eval_info(valid_eval_dir)
    spec.evaluation.n_episodes = 3

    gate = check_validity(raw_run, parsed_info, spec)

    assert gate.status == "failed"
    assert gate.checks["expected_episode_count"]["passed"] is False


def test_validity_gate_fails_nan_primary_metric(spec: EvaluationSpec, tmp_path: Path) -> None:
    """A NaN success rate fails validity when NaN is disallowed."""
    data = {
        "pc_success": float("nan"),
        "episodes": [],
    }
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    (output_dir / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")

    raw_run = SimpleNamespace(exit_code=0)
    parsed_info = parse_eval_info(output_dir)

    gate = check_validity(raw_run, parsed_info, spec)
    assert gate.status == "failed"
    assert gate.checks["primary_metric_finite"]["passed"] is False


def test_performance_gate_passes(spec: EvaluationSpec) -> None:
    """A result above the threshold passes the performance gate."""
    result = EvaluationResultV2(
        run_id="r1",
        task_id="t1",
        policy_id="p1",
        adapter="lerobot_eval",
        status="completed",
        primary_metric="success_rate",
        metrics={"success_rate": 0.8},
    )
    spec.performance_gates.minimum_success_rate = 0.6

    gate = check_performance(result, spec)

    assert isinstance(gate, PerformanceGate)
    assert gate.status == "passed"
    assert gate.reason is None


def test_performance_gate_fails_below_threshold(spec: EvaluationSpec) -> None:
    """A result below the threshold fails with a descriptive reason."""
    result = EvaluationResultV2(
        run_id="r1",
        task_id="t1",
        policy_id="p1",
        adapter="lerobot_eval",
        status="completed",
        primary_metric="success_rate",
        metrics={"success_rate": 0.4},
    )
    spec.performance_gates.minimum_success_rate = 0.6

    gate = check_performance(result, spec)

    assert gate.status == "failed"
    assert "success_rate=0.4" in gate.reason
    assert "minimum_success_rate=0.6" in gate.reason


def test_performance_gate_checks_macro_task_rate(spec: EvaluationSpec) -> None:
    """The macro-task success rate threshold is checked independently."""
    result = EvaluationResultV2(
        run_id="r1",
        task_id="t1",
        policy_id="p1",
        adapter="lerobot_eval",
        status="completed",
        metrics={
            "success_rate": 0.8,
            "macro_task_success_rate": 0.3,
        },
    )
    spec.performance_gates.minimum_success_rate = 0.6
    spec.performance_gates.minimum_macro_task_success_rate = 0.5

    gate = check_performance(result, spec)

    assert gate.status == "failed"
    assert "macro_task_success_rate" in gate.reason


def test_performance_gate_allows_unset_thresholds(spec: EvaluationSpec) -> None:
    """When no thresholds are configured, performance passes by default."""
    result = EvaluationResultV2(
        run_id="r1",
        task_id="t1",
        policy_id="p1",
        adapter="lerobot_eval",
        status="completed",
        metrics={"success_rate": 0.0},
    )

    gate = check_performance(result, spec)

    assert gate.status == "passed"


def test_evaluation_result_v2_backward_compatible() -> None:
    """Old v1-style JSON can still be loaded into EvaluationResultV2."""
    v1_payload = {
        "run_id": "r1",
        "task_id": "t1",
        "policy_id": "p1",
        "adapter": "mock",
        "status": "completed",
        "metrics": {"success_rate": 0.5},
    }
    result = EvaluationResultV2.model_validate(v1_payload)
    assert result.schema_version == "rosclaw.darwin.evaluation_result.v2"
    assert result.metrics["success_rate"] == 0.5
    assert result.benchmark == {}
    assert result.primary_metric is None
