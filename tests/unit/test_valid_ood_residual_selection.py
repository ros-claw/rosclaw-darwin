#!/usr/bin/env python3
"""Unit tests for Sprint 7 valid OOD residual / adaptation selection logic.

These tests verify subtask selection, adaptation_delta calculation, and claim
classification — all without Docker.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_RUNNER_PATH = Path("scripts/ablations/run_valid_ood_residual_adaptation.py")


def _load_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_valid_ood_residual_adaptation", _RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_valid_ood_residual_adaptation"] = module
    spec.loader.exec_module(module)
    return module


_runner = _load_runner_module()


def _make_summary_entry(
    task_id: str = "task_1",
    subtask: str = "lift_only",
    condition: str = "baseline_v3",
    success_rate: float = 0.8,
    object_lifted_rate: float = 0.9,
    grasp_reached_rate: float = 0.85,
    slip_rate: float = 0.1,
    reachability_failure_rate: float = 0.0,
    gripper_aperture_limit_rate: float = 0.0,
    first_failing_subtask: str | None = "lift_only",
) -> dict:
    return {
        "task_id": task_id,
        "subtask": subtask,
        "condition": condition,
        "count": 20,
        "success_rate": success_rate,
        "object_lifted_rate": object_lifted_rate,
        "grasp_reached_rate": grasp_reached_rate,
        "slip_rate": slip_rate,
        "reachability_failure_rate": reachability_failure_rate,
        "gripper_aperture_limit_rate": gripper_aperture_limit_rate,
        "first_failing_subtask": first_failing_subtask,
    }


def test_select_subtasks_basic():
    """A subtask with baseline success < 1.0, low aperture limit, and known first_failing_subtask should be selected."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_only",
                condition="baseline_v3",
                success_rate=0.8,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="lift_only",
            ),
        }
    }
    selected = _runner._select_subtasks(
        summary, ["task_1"], _runner._DEFAULT_SELECTION_THRESHOLDS
    )
    assert len(selected) == 1
    assert selected[0][0] == "task_1"
    assert selected[0][1] == "lift_only"


def test_select_subtasks_saturated_excluded():
    """A subtask with baseline success_rate >= 0.99 should be excluded."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_only",
                success_rate=1.0,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="lift_hold",
            ),
            "task_1__lift_hold__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_hold",
                success_rate=0.8,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="lift_hold",
            ),
        }
    }
    selected = _runner._select_subtasks(
        summary, ["task_1"], _runner._DEFAULT_SELECTION_THRESHOLDS
    )
    assert len(selected) == 1
    assert selected[0][1] == "lift_hold"


def test_select_subtasks_aperture_excluded():
    """A subtask with gripper_aperture_limit_rate >= 0.5 should be excluded."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_only",
                success_rate=0.8,
                gripper_aperture_limit_rate=0.6,
                first_failing_subtask="lift_only",
            ),
        }
    }
    selected = _runner._select_subtasks(
        summary, ["task_1"], _runner._DEFAULT_SELECTION_THRESHOLDS
    )
    assert len(selected) == 0


def test_select_subtasks_no_first_failing_excluded():
    """A subtask with first_failing_subtask=None should be excluded."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_only",
                success_rate=0.8,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask=None,
            ),
        }
    }
    selected = _runner._select_subtasks(
        summary, ["task_1"], _runner._DEFAULT_SELECTION_THRESHOLDS
    )
    assert len(selected) == 0


def test_select_subtasks_before_boundary_excluded():
    """Subtasks before the first_failing_subtask should be excluded."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_only",
                success_rate=1.0,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="yaw_0",
            ),
            "task_1__lift_hold__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_hold",
                success_rate=1.0,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="yaw_0",
            ),
            "task_1__yaw_0__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="yaw_0",
                success_rate=0.7,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="yaw_0",
            ),
        }
    }
    selected = _runner._select_subtasks(
        summary, ["task_1"], _runner._DEFAULT_SELECTION_THRESHOLDS
    )
    assert len(selected) == 1
    assert selected[0][1] == "yaw_0"


def test_select_subtasks_multiple_tasks():
    """Selection should work across multiple tasks."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": _make_summary_entry(
                task_id="task_1",
                subtask="lift_only",
                success_rate=0.8,
                gripper_aperture_limit_rate=0.0,
                first_failing_subtask="lift_only",
            ),
            "task_2__yaw_90__baseline_v3": _make_summary_entry(
                task_id="task_2",
                subtask="yaw_90",
                success_rate=0.6,
                gripper_aperture_limit_rate=0.1,
                first_failing_subtask="yaw_90",
            ),
        }
    }
    selected = _runner._select_subtasks(
        summary, ["task_1", "task_2"], _runner._DEFAULT_SELECTION_THRESHOLDS
    )
    assert len(selected) == 2
    task_ids = [s[0] for s in selected]
    assert "task_1" in task_ids
    assert "task_2" in task_ids


def test_compute_adaptation_delta_positive():
    """adaptation_delta should be positive when condition outperforms baseline."""
    rows = [
        {
            "task_id": "task_1",
            "subtask": "lift_only",
            "condition": "baseline_v3",
            "seed": 0,
            "success_rate": 0.8,
        },
        {
            "task_id": "task_1",
            "subtask": "lift_only",
            "condition": "object_geometry_adapter",
            "seed": 0,
            "success_rate": 1.0,
        },
    ]
    delta = _runner._compute_adaptation_delta(
        rows, "task_1", "lift_only", "object_geometry_adapter", 0
    )
    assert delta == pytest.approx(0.2)


def test_compute_adaptation_delta_negative():
    """adaptation_delta should be negative when condition underperforms baseline."""
    rows = [
        {
            "task_id": "task_1",
            "subtask": "lift_only",
            "condition": "baseline_v3",
            "seed": 1,
            "success_rate": 1.0,
        },
        {
            "task_id": "task_1",
            "subtask": "lift_only",
            "condition": "object_geometry_adapter",
            "seed": 1,
            "success_rate": 0.5,
        },
    ]
    delta = _runner._compute_adaptation_delta(
        rows, "task_1", "lift_only", "object_geometry_adapter", 1
    )
    assert delta == -0.5


def test_compute_adaptation_delta_missing_baseline():
    """adaptation_delta should be None when baseline row is missing."""
    rows = [
        {
            "task_id": "task_1",
            "subtask": "lift_only",
            "condition": "object_geometry_adapter",
            "seed": 0,
            "success_rate": 1.0,
        },
    ]
    delta = _runner._compute_adaptation_delta(
        rows, "task_1", "lift_only", "object_geometry_adapter", 0
    )
    assert delta is None


def test_classify_claim_baseline():
    """baseline_v3 condition should always return 'baseline' claim."""
    aggregated = {"by_task_subtask_condition": {}}
    claim = _runner._classify_claim(aggregated, "task_1", "lift_only", "baseline_v3", 0.8)
    assert claim == "baseline"


def test_classify_claim_no_gain():
    """When success_rate does not improve and object_lifted_rate does not improve, claim is 'no_gain'."""
    aggregated = {
        "by_task_subtask_condition": {
            "task_1__lift_only__object_geometry_adapter": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "object_geometry_adapter",
                "success_rate": 0.75,
                "object_lifted_rate": 0.8,
            },
            "task_1__lift_only__baseline_v3": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "baseline_v3",
                "success_rate": 0.8,
                "object_lifted_rate": 0.85,
            },
        }
    }
    claim = _runner._classify_claim(
        aggregated, "task_1", "lift_only", "object_geometry_adapter", 0.8
    )
    assert claim == "no_gain"


def test_classify_claim_boundary_advancement():
    """When only object_lifted_rate improves, claim is 'boundary_advancement'."""
    aggregated = {
        "by_task_subtask_condition": {
            "task_1__lift_only__object_geometry_adapter": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "object_geometry_adapter",
                "success_rate": 0.8,
                "object_lifted_rate": 0.95,
            },
            "task_1__lift_only__baseline_v3": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "baseline_v3",
                "success_rate": 0.8,
                "object_lifted_rate": 0.85,
            },
        }
    }
    claim = _runner._classify_claim(
        aggregated, "task_1", "lift_only", "object_geometry_adapter", 0.8
    )
    assert claim == "boundary_advancement"


def test_classify_claim_success_gain():
    """When success_rate improves by >= 5 percentage points, claim is 'success_gain'."""
    aggregated = {
        "by_task_subtask_condition": {
            "task_1__lift_only__object_geometry_adapter": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "object_geometry_adapter",
                "success_rate": 0.9,
                "object_lifted_rate": 0.85,
            },
            "task_1__lift_only__baseline_v3": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "baseline_v3",
                "success_rate": 0.8,
                "object_lifted_rate": 0.85,
            },
        }
    }
    claim = _runner._classify_claim(
        aggregated, "task_1", "lift_only", "object_geometry_adapter", 0.8
    )
    assert claim == "success_gain"


def test_classify_claim_candidate_transferable_skill():
    """When success_gain on >= 2 OOD variants, claim is 'candidate_transferable_skill'."""
    aggregated = {
        "by_task_subtask_condition": {
            "task_1__lift_only__object_geometry_adapter": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "object_geometry_adapter",
                "success_rate": 0.9,
                "object_lifted_rate": 0.85,
            },
            "task_1__lift_only__baseline_v3": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "baseline_v3",
                "success_rate": 0.8,
                "object_lifted_rate": 0.85,
            },
            "task_2__lift_only__object_geometry_adapter": {
                "task_id": "task_2",
                "subtask": "lift_only",
                "condition": "object_geometry_adapter",
                "success_rate": 0.95,
                "object_lifted_rate": 0.9,
            },
            "task_2__lift_only__baseline_v3": {
                "task_id": "task_2",
                "subtask": "lift_only",
                "condition": "baseline_v3",
                "success_rate": 0.7,
                "object_lifted_rate": 0.8,
            },
        }
    }
    claim = _runner._classify_claim(
        aggregated, "task_1", "lift_only", "object_geometry_adapter", 0.8
    )
    assert claim == "candidate_transferable_skill"


def test_classify_claim_missing_entry():
    """When the entry is missing from aggregated, claim is 'no_gain'."""
    aggregated = {"by_task_subtask_condition": {}}
    claim = _runner._classify_claim(
        aggregated, "task_1", "lift_only", "object_geometry_adapter", 0.8
    )
    assert claim == "no_gain"


def test_load_summary():
    """_load_summary should correctly parse a JSON file."""
    import tempfile

    data = {"key": "value", "nested": {"a": 1}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = Path(f.name)
    try:
        result = _runner._load_summary(path)
        assert result == data
    finally:
        path.unlink()
