"""Unit tests for reproducibility metadata helpers."""

from __future__ import annotations

import json

from rosclaw_darwin.evaluation.reproducibility import (
    collect_environment_info,
    collect_git_info,
    make_seed_info,
    persist_run_artifacts,
)
from rosclaw_darwin.evaluation.result import EvaluationResult


def test_collect_git_info_structure(tmp_path):
    # Use a temporary git repo so the helper is deterministic.
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=Test", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    info = collect_git_info(tmp_path)
    assert info["rosclaw_darwin_commit"] is not None
    assert info["rosclaw_darwin_branch"] in ("master", "main")
    assert isinstance(info["dirty"], bool)


def test_collect_environment_info_structure():
    info = collect_environment_info()
    assert "python_version" in info
    assert "timestamp" in info
    assert "hostname" in info
    assert info["timestamp"].endswith("Z")


def test_make_seed_info():
    info = make_seed_info(42, arena_seed_controlled=True, uncontrolled_randomness_notes="none")
    assert info["requested_seed"] == 42
    assert info["arena_seed_controlled"] is True
    assert info["uncontrolled_randomness_notes"] == "none"


def test_persist_run_artifacts(tmp_path):
    result = EvaluationResult(
        run_id="test_run_001",
        task_id="lift_object",
        policy_id="heuristic_servo_lift",
        adapter="arena",
        status="completed",
        metrics={"success_rate": 0.5, "progress": 0.75},
        failure_types={"target_not_reached_after_lift": 5},
        started_at="2026-06-15T10:00:00Z",
        finished_at="2026-06-15T10:05:00Z",
    )
    policy_config = {"policy_id": "heuristic_servo_lift", "type": "heuristic_servo_lift"}
    artifacts = persist_run_artifacts(
        tmp_path / "run",
        result,
        task_yaml="task: lift_object\n",
        policy_config=policy_config,
        command=["docker", "run", "rosclaw-darwin:arena-base"],
        seed=0,
        episode_metrics=[{"episode_id": 0, "success": True}],
        phase_traces=[{"episode_id": 0, "phases": ["APPROACH", "LIFT"]}],
        stdout="stdout content",
        stderr="stderr content",
    )

    assert (artifacts["result.json"]).exists()
    assert (artifacts["task.yaml"]).exists()
    assert (artifacts["policy.yaml"]).exists()
    assert (artifacts["summary.json"]).exists()
    assert (artifacts["command.json"]).exists()
    assert (artifacts["episode_metrics.jsonl"]).exists()
    assert (artifacts["phase_traces.jsonl"]).exists()
    assert (artifacts["stdout.log"]).exists()
    assert (artifacts["stderr.log"]).exists()
    assert (artifacts["git_info.json"]).exists()
    assert (artifacts["docker_info.json"]).exists()
    assert (artifacts["environment_info.json"]).exists()
    assert (artifacts["seed_info.json"]).exists()

    summary = json.loads(artifacts["summary.json"].read_text())
    assert summary["task_id"] == "lift_object"
    assert summary["metrics"]["success_rate"] == 0.5

    seed_info = json.loads(artifacts["seed_info.json"].read_text())
    assert seed_info["requested_seed"] == 0

    episode_line = json.loads(artifacts["episode_metrics.jsonl"].read_text())
    assert episode_line["episode_id"] == 0
