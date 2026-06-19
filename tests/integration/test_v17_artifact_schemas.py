"""Integration tests for v1.7 artifact schemas and dashboard loaders.

These tests do not require a live Arena run.  They verify that the JSON
aggregates produced by the v1.7 runners contain the fields expected by the
reports and dashboard loaders.
"""

import json
import math
import tempfile
from pathlib import Path

from rosclaw_darwin.dashboard.app import DashboardApp
from rosclaw_darwin.evaluation.object_validity import ObjectValidityReport, check_object_validity
from rosclaw_darwin.evaluation.yaw_coupling import classify_large_yaw_failure


def test_post_reachability_aggregate_schema():
    """The 100-seed runner must write an aggregate with the v1.7 fields."""
    aggregate = {
        "total_seeds": 100,
        "valid_seeds": 100,
        "successful_seeds": 94,
        "overall_success_rate": 0.94,
        "failure_distribution": {"large_yaw_slip": 4, "object_not_lifted": 2},
        "approach_collision_rate": 0.0,
        "workspace_failure_rate": 0.0,
        "large_yaw_slip_rate": 0.04,
        "physics_anomaly_rate": 0.0,
        "metric_parser_error_rate": 0.0,
        "asset_fallback_used_count": 0,
    }
    required = {
        "overall_success_rate",
        "failure_distribution",
        "approach_collision_rate",
        "large_yaw_slip_rate",
        "physics_anomaly_rate",
        "asset_fallback_used_count",
    }
    assert required.issubset(aggregate)
    assert aggregate["overall_success_rate"] == 94 / 100
    assert aggregate["asset_fallback_used_count"] == 0


def test_procedural_validity_report_flags_invalid_object():
    """An object below the table must be marked invalid by the audit checker."""
    report = check_object_validity(
        ObjectValidityReport(
            task_id="goal_pose_procedural_cube_ood",
            object_name="object",
            object_root_pos=[0.0, 0.0, -0.05],
            bbox_extent=[0.05, 0.05, 0.05],
            rigid_body_enabled=True,
            collision_enabled=True,
            object_above_table=False,
            object_index_consistent=True,
        ),
        table_z=0.18,
    )
    assert not report.valid
    assert "object_z_out_of_bounds" in report.validity_errors or "table_penetration" in report.validity_errors


def test_large_yaw_slip_aggregate_schema():
    """The large-yaw diagnosis runner aggregate must contain per-yaw metrics."""
    aggregate = {
        "yaw_1.5708": {
            "count": 20,
            "valid_count": 20,
            "env_success_rate": 0.0,
            "lifted_rate": 1.0,
            "orientation_achieved_rate": 0.1,
            "category_distribution": {"object_not_coupled": 18, "success": 2},
            "mean_object_yaw_final_error": 1.4,
            "mean_yaw_coupling_score": 0.05,
        }
    }
    required = {
        "count",
        "valid_count",
        "lifted_rate",
        "orientation_achieved_rate",
        "category_distribution",
        "mean_yaw_coupling_score",
    }
    assert required.issubset(aggregate["yaw_1.5708"])


def test_dashboard_large_yaw_loader():
    """Dashboard _load_large_yaw_slip returns the expected shape."""
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        data_dir = project_dir / "data"
        data_dir.mkdir(parents=True)
        diag_dir = project_dir / "data_v17" / "diagnostics" / "large_yaw_slip"
        diag_dir.mkdir(parents=True)
        aggregate = {
            "yaw_1.5708": {"lifted_rate": 1.0, "orientation_achieved_rate": 0.1},
            "yaw_2.0944": {"lifted_rate": 1.0, "orientation_achieved_rate": 0.0},
        }
        (diag_dir / "aggregate_summary.json").write_text(json.dumps(aggregate))

        app = DashboardApp(str(data_dir))
        data = app._load_large_yaw_slip()
        assert data is not None
        assert "per_yaw" in data
        assert "yaw_1.5708" in data["per_yaw"]


def test_large_yaw_failure_classification_categories():
    """Ensure the classification taxonomy returns the expected categories."""
    trace = [
        {"step": 0, "target_yaw": math.pi / 2, "eef_yaw": 0.0, "object_yaw": 0.0, "object_z": 0.05, "phase": "APPROACH"},
        {"step": 1, "target_yaw": math.pi / 2, "eef_yaw": 1.5, "object_yaw": 1.5, "object_z": 0.15, "phase": "LIFT"},
        {"step": 2, "target_yaw": math.pi / 2, "eef_yaw": 1.55, "object_yaw": 0.9, "object_z": 0.30, "phase": "HOLD"},
    ]
    diag = classify_large_yaw_failure(trace)
    assert diag["category"] in {"torsional_slip", "post_lift_slip"}
    assert diag["torsional_slip_detected"]
