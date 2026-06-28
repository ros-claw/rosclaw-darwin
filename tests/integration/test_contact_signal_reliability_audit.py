#!/usr/bin/env python3
"""Integration test for contact-signal reliability audit CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_trace(trace_dir: Path, frames: list[dict]) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    with (trace_dir / "trace.jsonl").open("w", encoding="utf-8") as f:
        for frame in frames:
            f.write(json.dumps(frame) + "\n")


@pytest.fixture
def runner_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "diagnostics" / "run_contact_signal_reliability_audit.py"


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_from_traces_produces_summary(runner_path: Path, project_root: Path, tmp_path: Path):
    trace_root = tmp_path / "traces"
    _write_trace(
        trace_root / "seed_000",
        [
            {"step": 0, "phase": "GRASP", "contact_state": "likely_contact", "contact_confidence": 0.7},
            {"step": 1, "phase": "LIFT_VERIFY", "contact_state": "likely_contact", "contact_confidence": 0.7},
            {"step": 2, "phase": "HOLD", "contact_state": "likely_contact", "contact_confidence": 0.7},
        ],
    )
    _write_trace(
        trace_root / "seed_001",
        [
            {"step": 0, "phase": "GRASP", "contact_state": "weak_contact_no_lift", "contact_confidence": 0.6},
            {"step": 1, "phase": "CONTACT_VERIFY", "contact_state": "likely_contact", "contact_confidence": 0.7, "contact_proxy": "likely_contact"},
        ],
    )

    out_dir = tmp_path / "audit_out"
    cmd = [
        sys.executable,
        str(runner_path),
        "--from-traces",
        str(trace_root),
        "--out-dir",
        str(out_dir),
    ]
    env = {"PYTHONPATH": str(project_root)}
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    summary_path = out_dir / "aggregate_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["num_seeds"] == 2
    assert summary["overall_coverage_rate"] == 1.0
    assert summary["phases"]["GRASP"]["total_steps"] == 2
    assert summary["phases"]["LIFT"]["total_steps"] == 1
    assert summary["phases"]["CONTACT_VERIFY"]["legacy_proxy_agreement_rate"] == 1.0

    csv_path = out_dir / "per_seed_results.csv"
    assert csv_path.exists()


def test_from_traces_missing_directory_fails(runner_path: Path, project_root: Path, tmp_path: Path):
    out_dir = tmp_path / "audit_out"
    cmd = [
        sys.executable,
        str(runner_path),
        "--from-traces",
        str(tmp_path / "does_not_exist"),
        "--out-dir",
        str(out_dir),
    ]
    env = {"PYTHONPATH": str(project_root)}
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
