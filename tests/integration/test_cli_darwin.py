"""Integration tests for the Darwin v1.0 CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

CLI = [sys.executable, "-m", "rosclaw_darwin.cli.main", "darwin"]

TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
BASELINE = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
CANDIDATE = "configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_darwin_help():
    result = _run("--help")
    assert result.returncode == 0
    assert "validate-env" in result.stdout
    assert "pair-eval" in result.stdout


def test_validate_env_mock(tmp_path: Path):
    out = tmp_path / "validity"
    result = _run("validate-env", "--task", TASK, "--out", str(out), "--mock")
    assert result.returncode == 0, result.stderr
    validity_path = out / "task_validity.json"
    assert validity_path.exists()
    data = json.loads(validity_path.read_text())
    assert data["validity_status"] == "valid"
    assert data["benchmark_scope"] == "official_arena_asset"


def test_run_mock(tmp_path: Path):
    out = tmp_path / "runs"
    result = _run(
        "run",
        "--task", TASK,
        "--policy", BASELINE,
        "--seeds", "0:4",
        "--out", str(out),
        "--mock",
    )
    assert result.returncode == 0, result.stderr
    run_dirs = list(out.iterdir())
    assert run_dirs
    artifact_path = run_dirs[0] / "run_artifact.json"
    assert artifact_path.exists()
    data = json.loads(artifact_path.read_text())
    assert data["status"] == "completed"


def test_diagnose_mock(tmp_path: Path):
    out = tmp_path / "diagnose"
    result = _run("diagnose", "--run", str(tmp_path), "--out", str(out), "--mock")
    assert result.returncode == 0, result.stderr
    signature_path = out / "failure_signature.json"
    assert signature_path.exists()
    data = json.loads(signature_path.read_text())
    assert data["failure_type"] == "post_lift_slip"


def test_pair_eval_mock(tmp_path: Path):
    out = tmp_path / "paired"
    result = _run(
        "pair-eval",
        "--task", TASK,
        "--baseline", BASELINE,
        "--candidate", CANDIDATE,
        "--seeds", "0:4",
        "--out", str(out),
        "--mock",
    )
    assert result.returncode == 0, result.stderr
    summary_path = out / "paired_summary.json"
    assert summary_path.exists()
    data = json.loads(summary_path.read_text())
    assert "summary" in data


def test_promote_from_paired_summary(tmp_path: Path):
    paired_dir = tmp_path / "paired"
    result = _run(
        "pair-eval",
        "--task", TASK,
        "--baseline", BASELINE,
        "--candidate", CANDIDATE,
        "--seeds", "0:30",
        "--out", str(paired_dir),
        "--mock",
    )
    assert result.returncode == 0
    promo_dir = tmp_path / "promotions"
    result = _run(
        "promote",
        "--candidate", "seed24_micro_recovery",
        "--paired", str(paired_dir / "paired_summary.json"),
        "--out", str(promo_dir),
    )
    assert result.returncode == 0, result.stderr
    decision_path = promo_dir / "seed24_micro_recovery_promotion_decision.json"
    assert decision_path.exists()
    data = json.loads(decision_path.read_text())
    assert data["candidate_name"] == "seed24_micro_recovery"
    assert data["status"] == "candidate_recovery"


def test_card_generation(tmp_path: Path):
    out = tmp_path / "cards"
    result = _run(
        "card",
        "--candidate", "seed24_micro_recovery",
        "--out", str(out),
        "--mock",
    )
    assert result.returncode == 0, result.stderr
    yaml_path = out / "seed24_micro_recovery.card.yaml"
    md_path = out / "seed24_micro_recovery.card.md"
    assert yaml_path.exists()
    assert md_path.exists()
    data = yaml.safe_load(yaml_path.read_text())
    assert data["name"] == "seed24_micro_recovery"


def test_registry_list(tmp_path: Path):
    registry_dir = tmp_path / "registry"
    result = _run("registry", "list", "--registry", str(registry_dir))
    assert result.returncode == 0, result.stderr
    assert "Registry entries:" in result.stdout


def test_registry_add_and_show(tmp_path: Path):
    cards_dir = tmp_path / "cards"
    _run(
        "card",
        "--candidate", "seed24_micro_recovery",
        "--out", str(cards_dir),
        "--mock",
    )
    registry_dir = tmp_path / "registry"
    card_path = cards_dir / "seed24_micro_recovery.card.yaml"
    result = _run(
        "registry", "add",
        "--registry", str(registry_dir),
        "--name", "seed24_micro_recovery",
        "--card", str(card_path),
    )
    assert result.returncode == 0, result.stderr
    assert "candidate_recovery" in result.stdout

    result = _run(
        "registry", "show",
        "--registry", str(registry_dir),
        "--name", "seed24_micro_recovery",
    )
    assert result.returncode == 0, result.stderr
    assert "seed24_micro_recovery" in result.stdout
    assert "Allowed claims:" in result.stdout


def test_registry_recoveries(tmp_path: Path):
    cards_dir = tmp_path / "cards"
    _run(
        "card",
        "--candidate", "seed24_micro_recovery",
        "--out", str(cards_dir),
        "--mock",
    )
    registry_dir = tmp_path / "registry"
    card_path = cards_dir / "seed24_micro_recovery.card.yaml"
    _run(
        "registry", "add",
        "--registry", str(registry_dir),
        "--name", "seed24_micro_recovery",
        "--card", str(card_path),
    )
    result = _run(
        "registry", "recoveries",
        "--registry", str(registry_dir),
        "--task", "seed24",
    )
    assert result.returncode == 0, result.stderr
    assert "Enabled recoveries:" in result.stdout
    assert "seed24_micro_recovery" in result.stdout
    cards_dir = tmp_path / "cards"
    _run(
        "card",
        "--candidate", "seed24_micro_recovery",
        "--out", str(cards_dir),
        "--mock",
    )
    report_dir = tmp_path / "report"
    result = _run("report", "--out", str(report_dir), "--cards", str(cards_dir))
    assert result.returncode == 0, result.stderr
    index_path = report_dir / "report_index.json"
    assert index_path.exists()
    data = json.loads(index_path.read_text())
    assert data["card_count"] == 1
