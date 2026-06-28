#!/usr/bin/env python3
"""Unit tests for valid OOD subtask selection logic.

These tests verify canonical ordering, subtask task modifications, yaw override
injection, and first_failing_subtask aggregation — all without Docker.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, Primitive, SceneSpec, Task

_RUNNER_PATH = Path("scripts/diagnostics/run_valid_ood_subtask_decomposition.py")


def _load_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_valid_ood_subtask_decomposition", _RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_valid_ood_subtask_decomposition"] = module
    spec.loader.exec_module(module)
    return module


_runner = _load_runner_module()


@pytest.fixture
def dummy_task() -> Task:
    return Task(
        id="test_task",
        name="Test Task",
        scene=SceneSpec(name="table_simple", domain="table"),
        embodiment=EmbodimentSpec(robot="franka", control_mode="ik"),
        primitives=[Primitive(name="Orient", args={"target": "cube"})],
        eval=EvalSpec(
            max_steps=300,
            max_episodes=5,
            success_conditions=["pose_reached"],
        ),
    )


def test_subtask_canonical_order():
    """Canonical order must be lift_only < lift_hold < yaw_0 < yaw_90 < full."""
    order = _runner._SUBTASK_ORDER
    assert order == ["lift_only", "lift_hold", "yaw_0", "yaw_90", "full"]
    assert len(order) == len(set(order)), "Duplicate subtask names in canonical order"


def test_apply_subtask_lift_only(dummy_task: Task) -> None:
    _runner._apply_subtask(dummy_task, "lift_only")
    assert len(dummy_task.primitives) == 1
    assert dummy_task.primitives[0].name == "Lift"
    assert dummy_task.primitives[0].args.get("target") == "cube"
    assert dummy_task.eval.success_conditions == ["object_lifted"]


def test_apply_subtask_lift_hold(dummy_task: Task) -> None:
    _runner._apply_subtask(dummy_task, "lift_hold")
    assert len(dummy_task.primitives) == 2
    assert dummy_task.primitives[0].name == "Lift"
    assert dummy_task.primitives[1].name == "Hold"
    assert dummy_task.eval.success_conditions == ["object_lifted"]


def test_apply_subtask_yaw_0(dummy_task: Task) -> None:
    _runner._apply_subtask(dummy_task, "yaw_0")
    assert len(dummy_task.primitives) == 1
    assert dummy_task.primitives[0].name == "Orient"
    assert dummy_task.eval.success_conditions == ["pose_reached"]


def test_apply_subtask_yaw_90(dummy_task: Task) -> None:
    _runner._apply_subtask(dummy_task, "yaw_90")
    assert len(dummy_task.primitives) == 1
    assert dummy_task.primitives[0].name == "Orient"
    assert dummy_task.eval.success_conditions == ["pose_reached"]


def test_apply_subtask_yaw_120(dummy_task: Task) -> None:
    _runner._apply_subtask(dummy_task, "yaw_120")
    assert len(dummy_task.primitives) == 1
    assert dummy_task.primitives[0].name == "Orient"
    assert dummy_task.eval.success_conditions == ["pose_reached"]


def test_apply_subtask_full(dummy_task: Task) -> None:
    _runner._apply_subtask(dummy_task, "full")
    assert len(dummy_task.primitives) == 1
    assert dummy_task.primitives[0].name == "Orient"
    assert dummy_task.eval.success_conditions == ["pose_reached"]


def test_build_policy_config_yaw_0_override() -> None:
    """yaw_0 must inject target_yaw_override=0.0 into policy_config_dict."""
    from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry

    base = {"policy_id": "test", "policy_config_dict": {}}
    geo = ObjectGeometry(width=0.05, depth=0.05, height=0.05)
    cfg = _runner._build_policy_config(base, "baseline_v3", geo, "yaw_0")
    assert cfg["policy_config_dict"]["target_yaw_override"] == 0.0


def test_build_policy_config_yaw_90_override() -> None:
    """yaw_90 must inject target_yaw_override=1.5708 into policy_config_dict."""
    from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry

    base = {"policy_id": "test", "policy_config_dict": {}}
    geo = ObjectGeometry(width=0.05, depth=0.05, height=0.05)
    cfg = _runner._build_policy_config(base, "baseline_v3", geo, "yaw_90")
    assert cfg["policy_config_dict"]["target_yaw_override"] == 1.5708


def test_build_policy_config_yaw_120_override() -> None:
    """yaw_120 must inject target_yaw_override=2.0944 into policy_config_dict."""
    from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry

    base = {"policy_id": "test", "policy_config_dict": {}}
    geo = ObjectGeometry(width=0.05, depth=0.05, height=0.05)
    cfg = _runner._build_policy_config(base, "baseline_v3", geo, "yaw_120")
    assert cfg["policy_config_dict"]["target_yaw_override"] == 2.0944


def test_build_policy_config_full_no_override() -> None:
    """full must NOT inject target_yaw_override."""
    from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry

    base = {"policy_id": "test", "policy_config_dict": {}}
    geo = ObjectGeometry(width=0.05, depth=0.05, height=0.05)
    cfg = _runner._build_policy_config(base, "baseline_v3", geo, "full")
    assert "target_yaw_override" not in cfg["policy_config_dict"]


def test_build_policy_config_best_combined() -> None:
    """best_combined must enable all three adaptation mechanisms."""
    from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry

    base = {"policy_id": "test", "policy_config_dict": {}}
    geo = ObjectGeometry(width=0.06, depth=0.06, height=0.06, mass=0.06)
    cfg = _runner._build_policy_config(base, "best_combined", geo, "full")
    pcd = cfg["policy_config_dict"]
    assert pcd["use_object_geometry_adaptation"] is True
    assert pcd["object_geometry"] == _runner._size_only_geometry(geo).to_dict()
    assert pcd["enable_grip_quality_monitor"] is True
    assert pcd["micro_recovery_strategy"] == "lower_reclose"
    assert pcd["enable_residual_policy"] is True
    assert pcd["residual_policy"] == "seed24_guard"
    assert pcd["residual_enabled_phases"] == ["GRASP", "CONTACT_VERIFY", "PRE_LIFT"]


def test_first_failing_subtask_aggregation() -> None:
    """first_failing_subtask should be the first canonical subtask where
    baseline_v3 success_rate < 1.0."""
    # Synthetic rows: all baseline_v3 seeds succeed except yaw_0 where one fails.
    rows = []
    for subtask in _runner._SUBTASK_ORDER:
        for seed in range(3):
            success = 1.0 if subtask != "yaw_0" else (1.0 if seed == 0 else 0.0)
            rows.append(
                {
                    "task_id": "task_1",
                    "variant": "task_1",
                    "subtask": subtask,
                    "condition": "baseline_v3",
                    "seed": seed,
                    "status": "completed",
                    "success_rate": success,
                    "object_lifted": True,
                    "grasp_reached": True,
                    "slip_detected": False,
                    "reachability_failure": False,
                    "gripper_aperture_limit": False,
                    "run_id": f"run_{seed}",
                }
            )
    # Add a different condition row to verify it doesn't affect baseline.
    rows.append(
        {
            "task_id": "task_1",
            "variant": "task_1",
            "subtask": "lift_only",
            "condition": "object_geometry_adapter",
            "seed": 0,
            "status": "completed",
            "success_rate": 1.0,
            "object_lifted": True,
            "grasp_reached": True,
            "slip_detected": False,
            "reachability_failure": False,
            "gripper_aperture_limit": False,
            "run_id": "run_other",
        }
    )

    summary = _runner._aggregate(rows, ["task_1"], _runner._SUBTASK_ORDER, ["baseline_v3", "object_geometry_adapter"])
    # Check that first_failing_subtask is "yaw_0" for baseline entries.
    for key, entry in summary["by_task_subtask_condition"].items():
        if entry["condition"] == "baseline_v3":
            assert entry["first_failing_subtask"] == "yaw_0"
        else:
            # Non-baseline conditions should also have the field (computed from baseline).
            assert entry["first_failing_subtask"] == "yaw_0"


def test_first_failing_subtask_all_pass() -> None:
    """If all baseline_v3 subtasks pass, first_failing_subtask is None."""
    rows = []
    for subtask in _runner._SUBTASK_ORDER:
        for seed in range(3):
            rows.append(
                {
                    "task_id": "task_2",
                    "variant": "task_2",
                    "subtask": subtask,
                    "condition": "baseline_v3",
                    "seed": seed,
                    "status": "completed",
                    "success_rate": 1.0,
                    "object_lifted": True,
                    "grasp_reached": True,
                    "slip_detected": False,
                    "reachability_failure": False,
                    "gripper_aperture_limit": False,
                    "run_id": f"run_{seed}",
                }
            )
    summary = _runner._aggregate(rows, ["task_2"], _runner._SUBTASK_ORDER, ["baseline_v3"])
    for entry in summary["by_task_subtask_condition"].values():
        assert entry["first_failing_subtask"] is None


def test_first_failing_subtask_lift_only_fails() -> None:
    """If lift_only fails, first_failing_subtask is lift_only."""
    rows = []
    for subtask in _runner._SUBTASK_ORDER:
        for seed in range(3):
            success = 1.0 if subtask != "lift_only" else 0.0
            rows.append(
                {
                    "task_id": "task_3",
                    "variant": "task_3",
                    "subtask": subtask,
                    "condition": "baseline_v3",
                    "seed": seed,
                    "status": "completed",
                    "success_rate": success,
                    "object_lifted": False,
                    "grasp_reached": False,
                    "slip_detected": False,
                    "reachability_failure": False,
                    "gripper_aperture_limit": False,
                    "run_id": f"run_{seed}",
                }
            )
    summary = _runner._aggregate(rows, ["task_3"], _runner._SUBTASK_ORDER, ["baseline_v3"])
    for entry in summary["by_task_subtask_condition"].values():
        assert entry["first_failing_subtask"] == "lift_only"


def test_compute_trace_bools_lifted() -> None:
    """object_lifted should be True when object_z increases by > 0.03."""
    trace = [
        {"object_z": 0.05, "phase": "APPROACH"},
        {"object_z": 0.05, "phase": "GRASP"},
        {"object_z": 0.12, "phase": "LIFT"},
    ]
    result = _runner._compute_trace_bools(trace)
    assert result["object_lifted"] is True
    assert result["grasp_reached"] is True


def test_compute_trace_bools_not_lifted() -> None:
    """object_lifted should be False when z delta is <= 0.03."""
    trace = [
        {"object_z": 0.05, "phase": "APPROACH"},
        {"object_z": 0.05, "phase": "GRASP"},
        {"object_z": 0.06, "phase": "LIFT"},
    ]
    result = _runner._compute_trace_bools(trace)
    assert result["object_lifted"] is False


def test_compute_trace_bools_slip_detected() -> None:
    trace = [
        {"object_z": 0.05, "slip_score": 0.2},
        {"object_z": 0.05, "slip_score": 0.8},
    ]
    result = _runner._compute_trace_bools(trace)
    assert result["slip_detected"] is True


def test_compute_trace_bools_reachability_failure() -> None:
    trace = [
        {"phase": "APPROACH"},
        {"phase": "REACHABILITY_FAILURE", "reason": "joint limit"},
    ]
    result = _runner._compute_trace_bools(trace)
    assert result["reachability_failure"] is True


def test_compute_trace_bools_aperture_limit() -> None:
    trace = [
        {"phase": "GRASP", "reason": "gripper aperture too wide"},
    ]
    result = _runner._compute_trace_bools(trace)
    assert result["gripper_aperture_limit"] is True


def test_parse_seeds_range() -> None:
    assert _runner._parse_seeds(["0:2"]) == [0, 1, 2]


def test_parse_seeds_multiple() -> None:
    assert _runner._parse_seeds(["0:1", "5", "10:11"]) == [0, 1, 5, 10, 11]


def test_parse_seeds_single() -> None:
    assert _runner._parse_seeds(["42"]) == [42]


def test_parse_seeds_comma() -> None:
    assert _runner._parse_seeds(["0,1,2"]) == [0, 1, 2]
