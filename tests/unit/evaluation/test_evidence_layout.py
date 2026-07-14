"""Tests that the run evidence directory layout matches the P3 contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from rosclaw_darwin.evaluation.backends.lerobot import LeRobotEvalBackend


def _make_eval_info(tmp_path: Path) -> Path:
    data = {
        "pc_success": 50.0,
        "avg_sum_reward": 0.75,
        "avg_max_reward": 0.9,
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
                "seed": 42,
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
                "seed": 43,
            },
        ],
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def _make_spec(n_episodes: int = 2) -> dict:
    return {
        "id": "pusht_layout_test",
        "backend": "lerobot_eval",
        "runtime": {"python": "python3"},
        "policy": {"path": "lerobot/diffusion_pusht", "device": "cpu"},
        "environment": {"type": "pusht", "batch_size": 2},
        "evaluation": {"n_episodes": n_episodes},
        "output": {"root": "data/eval_runs"},
    }


def _make_raw_run(output_dir: Path, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        run_id="eval_layout_001",
        output_dir=str(output_dir),
        returncode=returncode,
        stdout_path=str(output_dir / "raw" / "stdout.log"),
        stderr_path=str(output_dir / "raw" / "stderr.log"),
        eval_info_path=str(output_dir / "eval_info.json"),
        video_paths=[],
        provenance={},
    )


def test_evidence_layout_after_normalize(tmp_path: Path) -> None:
    backend = LeRobotEvalBackend()
    spec = _make_spec(n_episodes=2)
    spec["output"]["root"] = str(tmp_path / "runs")
    plan = backend.plan(spec)
    _make_eval_info(Path(plan.output_dir))

    raw_run = backend.execute(plan)

    # Simulate preflight written by the CLI before normalize().
    checks_dir = Path(raw_run.output_dir) / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    (checks_dir / "preflight.json").write_text(
        json.dumps({"status": "ok", "messages": []}), encoding="utf-8"
    )

    backend.normalize(raw_run, spec)
    output_dir = Path(raw_run.output_dir)

    assert (output_dir / "plan.json").exists()
    assert (output_dir / "provenance" / "runtime.json").exists()
    assert (output_dir / "provenance" / "policy.json").exists()
    assert (output_dir / "provenance" / "environment.json").exists()
    assert (output_dir / "provenance" / "benchmark.json").exists()
    assert (output_dir / "provenance" / "command.json").exists()
    assert (output_dir / "provenance" / "system.json").exists()
    assert (output_dir / "hashes.json").exists()
    assert (output_dir / "manifest.yaml").exists()
    assert (output_dir / "artifacts" / "predicted_videos").is_dir()

    manifest = yaml.safe_load((output_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "rosclaw.darwin.eval_manifest.v1"
    assert manifest["run_id"] == raw_run.run_id
    assert "created_at" in manifest
    assert manifest["plan_path"] == str(output_dir / "plan.json")
    assert manifest["provenance_dir"] == str(output_dir / "provenance")
    assert manifest["raw_dir"] == str(output_dir / "raw")
    assert manifest["normalized_dir"] == str(output_dir / "normalized")
    assert manifest["checks_dir"] == str(output_dir / "checks")
    assert manifest["hashes_path"] == str(output_dir / "hashes.json")
    assert manifest["result_path"] == str(output_dir / "normalized" / "evaluation_result.json")

    hashes = json.loads((output_dir / "hashes.json").read_text(encoding="utf-8"))
    for rel_path in ("plan.json", "eval_info.json", "normalized/evaluation_result.json"):
        assert rel_path in hashes
        file_path = output_dir / rel_path
        expected = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert hashes[rel_path] == expected

    plan = json.loads((output_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan["schema_version"] == "rosclaw.darwin.eval_plan.v1"
    assert plan["run_id"] == raw_run.run_id


def test_manifest_is_valid_yaml_not_json(tmp_path: Path) -> None:
    backend = LeRobotEvalBackend()
    spec = _make_spec(n_episodes=2)
    spec["output"]["root"] = str(tmp_path / "runs")
    plan = backend.plan(spec)
    _make_eval_info(Path(plan.output_dir))
    raw_run = backend.execute(plan)
    backend.normalize(raw_run, spec)
    output_dir = Path(raw_run.output_dir)

    text = (output_dir / "manifest.yaml").read_text(encoding="utf-8")
    # YAML should not contain JSON braces as the outer structure.
    assert not text.strip().startswith("{")
    manifest = yaml.safe_load(text)
    assert manifest["backend"] == "lerobot_eval"
