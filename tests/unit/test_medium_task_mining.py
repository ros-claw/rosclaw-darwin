"""Unit tests for valid OOD medium-task mining."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path("scripts/diagnostics/mine_valid_ood_medium_tasks.py")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "mine_valid_ood_medium_tasks", _SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["mine_valid_ood_medium_tasks"] = module
    spec.loader.exec_module(module)
    return module


_module = _load_module()


def _make_entry(
    task_id: str,
    success_rate: float | None,
    count: int = 20,
    first_failing: str | None = "yaw_90",
    slip_rate: float = 0.0,
    lifted_rate: float = 0.0,
    grasp_rate: float = 1.0,
    reachability_rate: float = 0.0,
    aperture_rate: float = 0.0,
    subtask: str = "full",
    condition: str = "baseline_v3",
) -> dict:
    return {
        "task_id": task_id,
        "subtask": subtask,
        "condition": condition,
        "count": count,
        "success_rate": success_rate,
        "object_lifted_rate": lifted_rate,
        "grasp_reached_rate": grasp_rate,
        "slip_rate": slip_rate,
        "reachability_failure_rate": reachability_rate,
        "gripper_aperture_limit_rate": aperture_rate,
        "first_failing_subtask": first_failing,
    }


def test_mines_medium_tasks():
    summary = {
        "by_task_subtask_condition": {
            "task_easy__full__baseline_v3": _make_entry("task_easy", 0.95),
            "task_medium__full__baseline_v3": _make_entry("task_medium", 0.55),
            "task_hard__full__baseline_v3": _make_entry("task_hard", 0.05),
        }
    }
    result = _module.mine_medium_tasks(summary)
    selected = {t["task_id"] for t in result["selected"]}
    rejected = {t["task_id"]: t["status"] for t in result["rejected"]}
    assert selected == {"task_medium"}
    assert rejected["task_easy"] == "too_easy"
    assert rejected["task_hard"] == "too_hard"


def test_respects_custom_thresholds():
    summary = {
        "by_task_subtask_condition": {
            "task_a__full__baseline_v3": _make_entry("task_a", 0.15),
            "task_b__full__baseline_v3": _make_entry("task_b", 0.85),
        }
    }
    result = _module.mine_medium_tasks(
        summary, success_min=0.1, success_max=0.9
    )
    selected = {t["task_id"] for t in result["selected"]}
    assert selected == {"task_a", "task_b"}


def test_invalid_geometry_rejected():
    summary = {
        "by_task_subtask_condition": {
            "task_geo__full__baseline_v3": _make_entry(
                "task_geo", 0.5, reachability_rate=0.6
            ),
        }
    }
    result = _module.mine_medium_tasks(summary)
    assert not result["selected"]
    assert result["rejected"][0]["status"] == "invalid_geometry"


def test_insufficient_data_rejected():
    summary = {
        "by_task_subtask_condition": {
            "task_low__full__baseline_v3": _make_entry(
                "task_low", 0.5, count=5
            ),
        }
    }
    result = _module.mine_medium_tasks(summary, min_seeds=10)
    assert not result["selected"]
    assert result["rejected"][0]["status"] == "insufficient_data"


def test_validity_set_filters_tasks():
    summary = {
        "by_task_subtask_condition": {
            "task_valid__full__baseline_v3": _make_entry("task_valid", 0.5),
            "task_invalid__full__baseline_v3": _make_entry("task_invalid", 0.5),
        }
    }
    result = _module.mine_medium_tasks(summary, validity_set={"task_valid"})
    selected = {t["task_id"] for t in result["selected"]}
    rejected = {t["task_id"]: t["status"] for t in result["rejected"]}
    assert selected == {"task_valid"}
    assert rejected["task_invalid"] == "invalid_validity"


def test_ignores_non_full_or_non_baseline_entries():
    summary = {
        "by_task_subtask_condition": {
            "task_x__lift_only__baseline_v3": _make_entry(
                "task_x", 0.5, subtask="lift_only"
            ),
            "task_x__full__object_geometry_adapter": _make_entry(
                "task_x", 0.5, condition="object_geometry_adapter"
            ),
        }
    }
    result = _module.mine_medium_tasks(summary)
    assert not result["selected"]
    assert not result["rejected"]


def test_dominant_failure_and_axis():
    summary = {
        "by_task_subtask_condition": {
            "task_slip__full__baseline_v3": _make_entry(
                "task_slip", 0.5, slip_rate=0.3, lifted_rate=0.7
            ),
        }
    }
    result = _module.mine_medium_tasks(summary)
    assert len(result["selected"]) == 1
    task = result["selected"][0]
    assert task["dominant_failure"] == "in_hand_slip"
    assert task["recommended_adaptation_axis"] == "slip_monitor / lower_speed_scale"


def test_recommended_axis_for_grasp_failure():
    summary = {
        "by_task_subtask_condition": {
            "task_grasp__full__baseline_v3": _make_entry(
                "task_grasp", 0.5, grasp_rate=0.3, first_failing="lift_only"
            ),
        }
    }
    result = _module.mine_medium_tasks(summary)
    task = result["selected"][0]
    assert task["recommended_adaptation_axis"] == "grip_quality / lower_reclose"


def test_difficulty_table_sorted():
    summary = {
        "by_task_subtask_condition": {
            "task_a__full__baseline_v3": _make_entry("task_a", 0.3),
            "task_b__full__baseline_v3": _make_entry("task_b", 0.7),
        }
    }
    result = _module.mine_medium_tasks(summary)
    rates = [r["baseline_success_rate"] for r in result["difficulty_table"]]
    assert rates == [0.7, 0.3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
