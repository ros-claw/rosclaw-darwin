"""Tests for the LeRobotEvalBackend runner behavior using fake executables."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest

from rosclaw_darwin.evaluation.backends.lerobot import LeRobotEvalBackend
from rosclaw_darwin.evaluation.backends.base import EvaluationPlan


def _make_spec(tmp_path: Path, fake_exe: Path, n_episodes: int = 2) -> dict:
    return {
        "id": "fake_runner_test",
        "backend": "lerobot_eval",
        "runtime": {"python": "python3", "lerobot_eval": str(fake_exe)},
        "policy": {"path": "fake/policy", "device": "cpu", "allow_network": False},
        "environment": {"type": "pusht", "batch_size": 2},
        "evaluation": {"n_episodes": n_episodes, "timeout_sec": 2},
        "output": {"root": str(tmp_path / "runs")},
    }


def _fake_eval_script(data: dict) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "output_dir = None\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('--output_dir='):\n"
        "        output_dir = arg.split('=', 1)[1]\n"
        "if not output_dir:\n"
        "    sys.exit(1)\n"
        "out = pathlib.Path(output_dir)\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"data = json.loads({json.dumps(json.dumps(data))})\n"
        "(out / 'eval_info.json').write_text(json.dumps(data))\n"
        "print('fake eval done')\n"
    )


def test_timeout_kills_process_group(tmp_path: Path) -> None:
    """A long-running child is terminated when the plan timeout expires."""
    slow_exe = tmp_path / "slow_eval"
    slow_exe.write_text(
        "#!/usr/bin/env python3\n"
        "import os, signal, time\n"
        "def handler(*args): pass\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    slow_exe.chmod(0o755)

    backend = LeRobotEvalBackend()
    spec = _make_spec(tmp_path, slow_exe, n_episodes=1)
    plan = backend.plan(spec)
    # Override timeout to avoid waiting the default.
    plan.timeout_sec = 1

    start = time.monotonic()
    raw_run = backend.execute(plan)
    elapsed = time.monotonic() - start

    assert raw_run.returncode is not None
    assert elapsed < 15


def test_fake_eval_timeout(tmp_path: Path) -> None:
    """A timed-out run is marked as backend_process_failed and produces evidence."""
    slow_exe = tmp_path / "slow_eval"
    slow_exe.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    slow_exe.chmod(0o755)

    backend = LeRobotEvalBackend()
    spec = _make_spec(tmp_path, slow_exe, n_episodes=1)
    plan = backend.plan(spec)
    plan.timeout_sec = 1

    raw_run = backend.execute(plan)
    result = backend.normalize(raw_run, spec)

    assert result.status == "backend_process_failed"
    assert (Path(raw_run.output_dir) / "raw" / "stdout.log").exists()
    assert (Path(raw_run.output_dir) / "raw" / "stderr.log").exists()


def test_fake_eval_multitask_result(tmp_path: Path) -> None:
    """A fake eval_info with multiple tasks is normalized into per-task rows."""
    data = {
        "pc_success": 50.0,
        "tasks": {
            "task_a": {
                "pc_success": 100.0,
                "avg_sum_reward": 0.9,
                "avg_max_reward": 1.0,
                "episodes": [
                    {"task": "task_a", "episode_index": 0, "success": True, "sum_reward": 0.9, "max_reward": 1.0},
                ],
            },
            "task_b": {
                "pc_success": 0.0,
                "avg_sum_reward": 0.2,
                "avg_max_reward": 0.3,
                "episodes": [
                    {"task": "task_b", "episode_index": 0, "success": False, "sum_reward": 0.2, "max_reward": 0.3},
                ],
            },
        }
    }
    fake_exe = tmp_path / "fake_lerobot_eval"
    fake_exe.write_text(_fake_eval_script(data), encoding="utf-8")
    fake_exe.chmod(0o755)

    backend = LeRobotEvalBackend()
    spec = _make_spec(tmp_path, fake_exe, n_episodes=2)
    plan = backend.plan(spec)
    raw_run = backend.execute(plan)
    result = backend.normalize(raw_run, spec)

    assert result.status == "completed"
    assert result.num_tasks == 2
    assert result.num_episodes == 2
    assert result.metrics["micro_success_rate"] == pytest.approx(0.5)
    assert result.metrics["macro_task_success_rate"] == pytest.approx(0.5)

    task_results_path = Path(result.task_results_path or "")
    assert task_results_path.exists()


def test_stdout_stderr_token_redaction(tmp_path: Path) -> None:
    """Sensitive tokens written to stdout/stderr are masked in captured logs."""
    leak_exe = tmp_path / "leak_eval"
    leak_exe.write_text(
        "#!/usr/bin/env python3\n"
        "print('HF_TOKEN=super_secret_value')\n"
        "print('api_key=another_secret')\n"
        "import pathlib, sys\n"
        "output_dir = [a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--output_dir=')][0]\n"
        "out = pathlib.Path(output_dir)\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'eval_info.json').write_text('{\"pc_success\":0,\"episodes\":[]}')\n",
        encoding="utf-8",
    )
    leak_exe.chmod(0o755)

    backend = LeRobotEvalBackend()
    spec = _make_spec(tmp_path, leak_exe, n_episodes=0)
    plan = backend.plan(spec)
    raw_run = backend.execute(plan)

    stdout = Path(raw_run.stdout_path).read_text(encoding="utf-8")
    assert "super_secret_value" not in stdout
    assert "another_secret" not in stdout
    assert "HF_TOKEN=***" in stdout
    assert "api_key=***" in stdout
