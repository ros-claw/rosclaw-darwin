"""Integration test for approach-collision diagnosis script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_diagnose_approach_collision_failures_cli(tmp_path: Path) -> None:
    out_dir = tmp_path / "paired"
    out_dir.mkdir()

    # Create a tiny paired summary with one approach-collision seed and one
    # grip-quality seed.
    summary = {
        "summary": {
            "task_id": "test_task",
            "seed_range": "0:1",
            "total_pairs": 2,
            "valid_pairs": 2,
        },
        "outcomes": [
            {
                "seed": 0,
                "delta_class": "unchanged_failure",
                "baseline_success": False,
                "candidate_success": False,
                "baseline_failure_type": "approach_collision",
                "candidate_failure_type": "approach_collision",
                "baseline_artifact_dir": str(out_dir / "seed_000" / "baseline"),
                "candidate_artifact_dir": str(out_dir / "seed_000" / "candidate"),
            },
            {
                "seed": 1,
                "delta_class": "rescued",
                "baseline_success": False,
                "candidate_success": True,
                "baseline_failure_type": "grip_force_insufficient",
                "candidate_failure_type": "none",
                "baseline_artifact_dir": str(out_dir / "seed_001" / "baseline"),
                "candidate_artifact_dir": str(out_dir / "seed_001" / "candidate"),
            },
        ],
    }
    summary_path = tmp_path / "paired_summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    # The script only reads failure_signature.json when it exists; create one
    # for the approach-collision seed to exercise the enrichment path.
    (out_dir / "seed_000" / "baseline").mkdir(parents=True)
    (out_dir / "seed_000" / "candidate").mkdir(parents=True)
    (out_dir / "seed_000" / "baseline" / "failure_signature.json").write_text(
        json.dumps({"failure_class": "approach_collision", "anomaly_tags": []}),
        encoding="utf-8",
    )
    (out_dir / "seed_000" / "candidate" / "failure_signature.json").write_text(
        json.dumps({"failure_class": "approach_collision", "anomaly_tags": []}),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "manifest" / "approach_collision_diagnosis.json"
    report_path = tmp_path / "report.md"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/diagnostics/diagnose_approach_collision_failures.py",
            "--paired-summary",
            str(summary_path),
            "--out-dir",
            str(manifest_path.parent),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["total_pairs"] == 2
    assert manifest["approach_collision_statistics"]["count"] == 1
    assert manifest["approach_collision_statistics"]["both"] == [0]
    assert manifest["approach_collision_seed_details"][0]["baseline_signature"]["failure_class"] == "approach_collision"

    report = report_path.read_text(encoding="utf-8")
    assert "Approach-collision dominated seeds:" in report
    assert "0" in report
