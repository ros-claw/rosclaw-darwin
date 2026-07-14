"""Unit tests for the LeRobot eval_info parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rosclaw_darwin.evaluation.parsers.lerobot_eval import (
    EvalErrorCode,
    EvalInfoError,
    parse_eval_info,
)
from rosclaw_darwin.evaluation.statistics import wilson_ci


@pytest.fixture
def single_task_eval_dir(tmp_path: Path) -> Path:
    """Minimal single-task eval_info.json with two episodes."""
    data = {
        "avg_sum_reward": 0.75,
        "avg_max_reward": 0.9,
        "pc_success": 50.0,
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
                "video_path": "videos/0.mp4",
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
                "video_path": "videos/1.mp4",
            },
        ],
        "extra_future_field": "ignored",
    }
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    (output_dir / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")
    return output_dir


def test_parse_single_task_success_rate(single_task_eval_dir: Path) -> None:
    """Parser normalizes pc_success into a [0,1] success rate."""
    info = parse_eval_info(single_task_eval_dir)

    assert info.success_rate == pytest.approx(0.5)
    assert info.pc_success == pytest.approx(50.0)
    assert info.avg_sum_reward == pytest.approx(0.75)
    assert info.eval_s == pytest.approx(12.5)
    assert len(info.episodes) == 2
    assert info.tasks["pusht_default"].success_rate == pytest.approx(0.5)
    assert info.tasks["pusht_default"].episodes[0].success is True
    assert info.raw["extra_future_field"] == "ignored"


def test_parse_episode_count_validation(single_task_eval_dir: Path) -> None:
    """Wrong expected episode count raises a structured error."""
    with pytest.raises(EvalInfoError) as exc_info:
        parse_eval_info(single_task_eval_dir, expected_episodes=3)
    assert exc_info.value.code == EvalErrorCode.episode_count_mismatch


def test_parse_wilson_ci_from_result(single_task_eval_dir: Path) -> None:
    """The parsed episode count can be fed into the Wilson CI helper."""
    info = parse_eval_info(single_task_eval_dir)
    successes = sum(1 for ep in info.episodes if ep.success)
    lower, upper = wilson_ci(successes, len(info.episodes))

    assert 0.0 <= lower <= upper <= 1.0
    assert lower < 0.5 < upper


def test_parse_missing_eval_info(tmp_path: Path) -> None:
    """A missing eval_info.json is reported with the correct error code."""
    with pytest.raises(EvalInfoError) as exc_info:
        parse_eval_info(tmp_path)
    assert exc_info.value.code == EvalErrorCode.eval_info_missing


def test_parse_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON is reported with the correct error code."""
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    (output_dir / "eval_info.json").write_text("not json", encoding="utf-8")

    with pytest.raises(EvalInfoError) as exc_info:
        parse_eval_info(output_dir)
    assert exc_info.value.code == EvalErrorCode.eval_info_invalid_json


def test_parse_episode_seed_and_suite(tmp_path: Path) -> None:
    """Episode-level seed and suite are captured and propagated."""
    data = {
        "suites": {
            "suite_1": {
                "groups": {
                    "group_1": {
                        "tasks": {
                            "task_1": {
                                "pc_success": 100.0,
                                "episodes": [
                                    {"task": "task_1", "episode_index": 0, "success": True, "sum_reward": 1.0, "max_reward": 1.0, "seed": 7},
                                ],
                            }
                        }
                    }
                }
            }
        }
    }
    output_dir = tmp_path / "eval"
    output_dir.mkdir()
    (output_dir / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")

    info = parse_eval_info(output_dir)
    assert len(info.episodes) == 1
    ep = info.episodes[0]
    assert ep.seed == 7
    assert ep.suite == "suite_1"
    assert info.tasks["task_1"].suite == "suite_1"
