"""Tests for LeRobotEvalBackend.normalize()."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rosclaw_darwin.evaluation.backends.lerobot import LeRobotEvalBackend
from rosclaw_darwin.evaluation.result_v2 import EvaluationResultV2


def _make_eval_info(tmp_path: Path, n_episodes: int = 2, pc_success: float = 50.0) -> Path:
    episodes = []
    for i in range(n_episodes):
        success = i < int(n_episodes * pc_success / 100.0)
        episodes.append(
            {
                "task": "pusht_default",
                "episode_index": i,
                "success": success,
                "sum_reward": 0.8 if success else 0.3,
                "max_reward": 1.0 if success else 0.4,
                "steps": 200,
                "terminated": success,
                "truncated": not success,
            }
        )
    data = {
        "avg_sum_reward": 0.75,
        "avg_max_reward": 0.9,
        "pc_success": pc_success,
        "eval_s": 12.5,
        "eval_ep_s": 6.25,
        "task": "pusht_default",
        "episodes": episodes,
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def _make_spec(n_episodes: int = 2) -> dict:
    return {
        "id": "pusht_normalize_test",
        "backend": "lerobot_eval",
        "runtime": {"python": "python3"},
        "policy": {"path": "lerobot/diffusion_pusht", "device": "cuda"},
        "environment": {"type": "pusht", "batch_size": 2},
        "evaluation": {"n_episodes": n_episodes},
        "output": {"root": "data/eval_runs"},
    }


def _make_raw_run(output_dir: Path, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        run_id="eval_test_001",
        output_dir=str(output_dir),
        returncode=returncode,
        stdout_path=str(output_dir / "raw" / "stdout.log"),
        stderr_path=str(output_dir / "raw" / "stderr.log"),
        eval_info_path=str(output_dir / "eval_info.json"),
        video_paths=[],
        provenance={},
    )


def test_normalize_success(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    eval_dir = _make_eval_info(output_dir, n_episodes=2, pc_success=50.0)
    raw_run = _make_raw_run(output_dir, returncode=0)
    backend = LeRobotEvalBackend()

    result = backend.normalize(raw_run, _make_spec(n_episodes=2))

    assert isinstance(result, EvaluationResultV2)
    assert result.status == "completed"
    assert result.metrics["success_rate"] == pytest.approx(0.5)
    assert result.metrics["micro_success_rate"] == pytest.approx(0.5)
    assert result.metrics["macro_task_success_rate"] == pytest.approx(0.5)
    assert result.validity_gate["status"] == "passed"
    assert result.performance_gate["status"] == "passed"
    assert "success_rate" in result.confidence_intervals
    assert (output_dir / "normalized" / "evaluation_result.json").exists()
    assert (output_dir / "checks" / "validity_gate.json").exists()


def test_normalize_invalid_on_returncode(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    _make_eval_info(output_dir, n_episodes=2, pc_success=50.0)
    raw_run = _make_raw_run(output_dir, returncode=1)
    backend = LeRobotEvalBackend()

    result = backend.normalize(raw_run, _make_spec(n_episodes=2))

    assert result.status == "backend_process_failed"
    assert result.validity_gate["status"] == "failed"


def test_normalize_invalid_on_episode_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    _make_eval_info(output_dir, n_episodes=2, pc_success=50.0)
    raw_run = _make_raw_run(output_dir, returncode=0)
    backend = LeRobotEvalBackend()

    result = backend.normalize(raw_run, _make_spec(n_episodes=3))

    assert result.status == "invalid"
    assert result.validity_gate["checks"]["expected_episode_count"]["passed"] is False


def test_normalize_persists_manifest_and_parquet(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    _make_eval_info(output_dir, n_episodes=4, pc_success=50.0)
    raw_run = _make_raw_run(output_dir, returncode=0)
    backend = LeRobotEvalBackend()

    backend.normalize(raw_run, _make_spec(n_episodes=4))

    assert (output_dir / "manifest.yaml").exists()
    assert (output_dir / "normalized" / "metric_definitions.json").exists()
    assert (output_dir / "normalized" / "task_results.jsonl").exists()
    assert (output_dir / "normalized" / "episode_results.jsonl").exists()
