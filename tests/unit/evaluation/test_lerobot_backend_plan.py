"""Unit tests for the LeRobot evaluation backend plan builder."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from rosclaw_darwin.evaluation.backends.lerobot import LeRobotEvalBackend


def _make_fake_lerobot_eval(tmp_path: Path) -> Path:
    exe = tmp_path / "lerobot-eval"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "print(json.dumps({'status': 'ok'}))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return exe


def _make_spec(tmp_path: Path, fake_exe: Path | None = None) -> dict:
    runtime = {"python": sys.executable}
    if fake_exe is not None:
        runtime["lerobot_eval"] = str(fake_exe)
    return {
        "backend": "lerobot_eval",
        "runtime": runtime,
        "policy": {
            "path": "/tmp/policy",
            "device": "cuda",
            "use_amp": True,
            "allow_network": False,
        },
        "environment": {"type": "pusht", "task": "task_0"},
        "evaluation": {
            "batch_size": 2,
            "n_episodes": 4,
            "start_seed": 42,
            "timeout_sec": 300,
        },
        "output": {"root": str(tmp_path / "runs")},
    }


@pytest.fixture
def backend() -> LeRobotEvalBackend:
    return LeRobotEvalBackend()


def test_plan_builds_expected_argv(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)

    plan = backend.plan(spec)

    assert plan.backend == "lerobot_eval"
    assert plan.command[0] == str(fake_exe)
    assert f"--policy.path={spec['policy']['path']}" in plan.command
    assert f"--env.type={spec['environment']['type']}" in plan.command
    assert f"--env.task={spec['environment']['task']}" in plan.command
    assert f"--eval.batch_size={spec['evaluation']['batch_size']}" in plan.command
    assert f"--eval.n_episodes={spec['evaluation']['n_episodes']}" in plan.command
    assert f"--seed={spec['evaluation']['start_seed']}" in plan.command
    assert f"--policy.device={spec['policy']['device']}" in plan.command
    assert "--policy.use_amp=true" in plan.command
    assert any(arg.startswith("--output_dir=") for arg in plan.command)


def test_plan_uses_specified_runtime(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)

    plan = backend.plan(spec)

    assert plan.runtime["python"] == sys.executable
    assert plan.runtime["lerobot_eval"] == str(fake_exe)


def test_plan_sets_output_dir_under_root(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)

    plan = backend.plan(spec)

    assert plan.output_dir.startswith(str(tmp_path / "runs"))
    assert Path(plan.output_dir).parent == tmp_path / "runs"


def test_plan_spec_hash_is_sha256(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)

    plan = backend.plan(spec)

    assert plan.spec_hash.startswith("sha256:")
    assert len(plan.spec_hash) == len("sha256:") + 64


def test_plan_command_is_argv_list_no_shell(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)

    plan = backend.plan(spec)

    assert isinstance(plan.command, list)
    assert all(isinstance(arg, str) for arg in plan.command)
    assert "|" not in " ".join(plan.command)
    assert "&&" not in " ".join(plan.command)


def test_plan_fallback_to_python_module(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    spec = _make_spec(tmp_path, fake_exe=None)

    plan = backend.plan(spec)

    assert plan.command[:3] == [sys.executable, "-m", "lerobot.scripts.lerobot_eval"]


def test_env_defaults_to_hub_offline(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)
    runtime = backend._resolve_runtime(spec)

    env = backend._build_env(spec, runtime)

    assert env["HF_HUB_OFFLINE"] == "1"


def test_env_unsets_hub_offline_when_network_allowed(
    tmp_path: Path, backend: LeRobotEvalBackend
) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)
    spec["policy"]["allow_network"] = True
    original = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    runtime = backend._resolve_runtime(spec)

    try:
        env = backend._build_env(spec, runtime)
        assert "HF_HUB_OFFLINE" not in env
    finally:
        if original is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = original


def test_plan_expected_tasks_and_episodes(tmp_path: Path, backend: LeRobotEvalBackend) -> None:
    fake_exe = _make_fake_lerobot_eval(tmp_path)
    spec = _make_spec(tmp_path, fake_exe)

    plan = backend.plan(spec)

    assert plan.expected_tasks == ["task_0"]
    assert plan.expected_episodes == 4
    assert plan.timeout_sec == 300
