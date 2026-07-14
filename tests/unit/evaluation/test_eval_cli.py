"""Tests for ``darwin eval`` CLI commands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rosclaw_darwin.cli.darwin_app import darwin_app
from rosclaw_darwin.evaluation.result_v2 import EvaluationResultV2


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_darwin_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ROSCLAW_DARWIN_HOME", str(tmp_path / "darwin_home"))


def test_eval_plan_prints_command(runner: CliRunner, tmp_path: Path) -> None:
    spec = {
        "schema_version": "rosclaw.darwin.eval_spec.v1",
        "id": "test_plan",
        "backend": "lerobot_eval",
        "runtime": {"python": "python3"},
        "policy": {"path": "lerobot/diffusion_pusht", "device": "cuda"},
        "environment": {"type": "pusht", "batch_size": 2},
        "evaluation": {"n_episodes": 2},
        "output": {"root": str(tmp_path / "runs")},
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = runner.invoke(darwin_app, ["eval", "plan", "--spec", str(spec_path)])

    assert result.exit_code == 0, result.output
    assert "rosclaw.darwin.eval_plan.v1" in result.output
    assert "--policy.path=lerobot/diffusion_pusht" in result.output
    assert "--eval.batch_size=2" in result.output


def test_eval_runtime_register_and_list(runner: CliRunner, isolated_darwin_home, tmp_path: Path) -> None:
    result = runner.invoke(
        darwin_app,
        [
            "eval",
            "runtime",
            "register",
            "--name",
            "test_runtime",
            "--mode",
            "external",
            "--python",
            "/usr/bin/python3",
            "--lerobot-eval",
            "/usr/bin/lerobot-eval",
            "--tag",
            "pusht",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Registered runtime" in result.output

    result = runner.invoke(darwin_app, ["eval", "runtime", "list"])
    assert result.exit_code == 0, result.output
    assert "test_runtime" in result.output
    assert "pusht" in result.output


def test_eval_validate_with_normalized_result(runner: CliRunner, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    norm_dir = run_dir / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    result = EvaluationResultV2(
        run_id="r1",
        task_id="pusht",
        policy_id="p1",
        adapter="lerobot_eval",
        status="completed",
        metrics={"success_rate": 0.5},
        validity_gate={"status": "passed"},
        performance_gate={"status": "passed"},
    )
    (norm_dir / "evaluation_result.json").write_text(
        json.dumps(result.model_dump(mode="json")), encoding="utf-8"
    )

    result_out = runner.invoke(darwin_app, ["eval", "validate", str(run_dir)])

    assert result_out.exit_code == 0, result_out.output
    assert "Validated run" in result_out.output
    assert "passed" in result_out.output


def test_eval_validate_fallback_to_raw_eval_info(runner: CliRunner, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "pc_success": 50.0,
        "task": "pusht_default",
        "episodes": [
            {"task": "pusht_default", "episode_index": 0, "success": True, "sum_reward": 0.8, "max_reward": 1.0},
            {"task": "pusht_default", "episode_index": 1, "success": False, "sum_reward": 0.3, "max_reward": 0.4},
        ],
    }
    (raw_dir / "eval_info.json").write_text(json.dumps(data), encoding="utf-8")

    result = runner.invoke(darwin_app, ["eval", "validate", str(run_dir)])

    assert result.exit_code == 0, result.output
    assert "Raw eval_info parsed" in result.output


def test_eval_run_with_fake_executable(runner: CliRunner, tmp_path: Path) -> None:
    """End-to-end run with a fake lerobot-eval executable."""
    fake_exe = tmp_path / "fake_lerobot_eval"
    fake_exe.write_text(
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
        "data = {\n"
        "    'pc_success': 50.0,\n"
        "    'avg_sum_reward': 0.75,\n"
        "    'avg_max_reward': 0.9,\n"
        "    'task': 'pusht_default',\n"
        "    'episodes': [\n"
        "        {'task': 'pusht_default', 'episode_index': 0, 'success': True, 'sum_reward': 0.8, 'max_reward': 1.0},\n"
        "        {'task': 'pusht_default', 'episode_index': 1, 'success': False, 'sum_reward': 0.7, 'max_reward': 0.8},\n"
        "    ],\n"
        "}\n"
        "(out / 'eval_info.json').write_text(json.dumps(data))\n"
        "print('fake eval done')\n",
        encoding="utf-8",
    )
    fake_exe.chmod(0o755)

    spec = {
        "schema_version": "rosclaw.darwin.eval_spec.v1",
        "id": "fake_run",
        "backend": "lerobot_eval",
        "runtime": {"python": "python3", "lerobot_eval": str(fake_exe)},
        "policy": {"path": "fake/policy", "device": "cpu", "allow_network": False},
        "environment": {"type": "pusht", "batch_size": 2},
        "evaluation": {"n_episodes": 2},
        "output": {"root": str(tmp_path / "runs")},
    }
    spec_path = tmp_path / "fake_spec.yaml"
    import json as _json
    spec_path.write_text(_json.dumps(spec), encoding="utf-8")

    result = runner.invoke(darwin_app, ["eval", "run", "--spec", str(spec_path), "--skip-probe"])

    assert result.exit_code == 0, result.output
    assert "fake_run" in result.output or "eval_" in result.output
    assert "50.00%" in result.output or "Success rate:" in result.output
    assert (tmp_path / "runs").exists()


def test_eval_inspect_prints_manifest_and_summary(runner: CliRunner, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    norm_dir = run_dir / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    result = EvaluationResultV2(
        run_id="r1",
        task_id="pusht",
        policy_id="p1",
        adapter="lerobot_eval",
        status="completed",
        metrics={"success_rate": 0.5},
        confidence_intervals={"success_rate": {"low": 0.1, "high": 0.9}},
        validity_gate={"status": "passed"},
        performance_gate={"status": "passed"},
    )
    (norm_dir / "evaluation_result.json").write_text(
        json.dumps(result.model_dump(mode="json")), encoding="utf-8"
    )
    (run_dir / "manifest.yaml").write_text(
        "schema_version: rosclaw.darwin.eval_manifest.v1\nrun_id: r1\nbackend: lerobot_eval\n",
        encoding="utf-8",
    )

    result_out = runner.invoke(darwin_app, ["eval", "inspect", str(run_dir)])

    assert result_out.exit_code == 0, result_out.output
    assert "r1" in result_out.output
    assert "Success rate:" in result_out.output


def test_eval_runtime_doctor_reports_probe(runner: CliRunner, isolated_darwin_home, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_exe = bin_dir / "lerobot-eval"
    fake_exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "print(json.dumps({\n"
        "    'status': 'ok',\n"
        "    'compatibility': 'compatible',\n"
        "    'lerobot_version': '0.0.1',\n"
        "    'torch_version': '2.0.0',\n"
        "    'policy': {'local_exists': True},\n"
        "    'environment': {'registered': True},\n"
        "    'device': {'available': True},\n"
        "    'messages': []\n"
        "}))\n",
        encoding="utf-8",
    )
    fake_exe.chmod(0o755)

    # Provide a minimal stub lerobot package so the probe can import it.
    pkg_dir = tmp_path / "lerobot"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("__version__ = '0.0.1'\n", encoding="utf-8")
    envs_dir = pkg_dir / "common" / "envs"
    envs_dir.mkdir(parents=True)
    (envs_dir / "__init__.py").write_text("", encoding="utf-8")
    (envs_dir / "utils.py").write_text("envs = {'pusht': None}\n", encoding="utf-8")

    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "config.json").write_text("{}", encoding="utf-8")

    original_path = os.environ.get("PATH", "")
    original_pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PATH"] = f"{bin_dir}:{original_path}"
    os.environ["PYTHONPATH"] = f"{tmp_path}:{original_pythonpath}".rstrip(":")
    try:
        register = runner.invoke(
            darwin_app,
            [
                "eval",
                "runtime",
                "register",
                "--name",
                "rt_doctor",
                "--mode",
                "external",
                "--python",
                sys.executable,
                "--lerobot-eval",
                str(fake_exe),
            ],
        )
        assert register.exit_code == 0, register.output

        result = runner.invoke(
            darwin_app,
            ["eval", "runtime", "doctor", "rt_doctor", "--policy", str(policy_dir)],
        )
    finally:
        os.environ["PATH"] = original_path
        if original_pythonpath:
            os.environ["PYTHONPATH"] = original_pythonpath
        else:
            os.environ.pop("PYTHONPATH", None)

    assert result.exit_code == 0, result.output
    assert "compatible" in result.output
    assert "rt_doctor" in result.output
    assert '"local_exists": true' in result.output


def test_eval_suite_runs_and_compares_specs(runner: CliRunner, tmp_path: Path) -> None:
    fake_exe = tmp_path / "fake_lerobot_eval"
    fake_exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "output_dir = [a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--output_dir=')][0]\n"
        "out = pathlib.Path(output_dir)\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "data = {'pc_success': 50.0, 'task': 'pusht_default', 'episodes': [\n"
        "    {'task': 'pusht_default', 'episode_index': 0, 'success': True, 'sum_reward': 0.8, 'max_reward': 1.0},\n"
        "    {'task': 'pusht_default', 'episode_index': 1, 'success': False, 'sum_reward': 0.7, 'max_reward': 0.8},\n"
        "]}\n"
        "(out / 'eval_info.json').write_text(json.dumps(data))\n",
        encoding="utf-8",
    )
    fake_exe.chmod(0o755)

    def make_spec(name: str) -> Path:
        spec = {
            "schema_version": "rosclaw.darwin.eval_spec.v1",
            "id": name,
            "backend": "lerobot_eval",
            "runtime": {"python": "python3", "lerobot_eval": str(fake_exe)},
            "policy": {"path": "fake/policy", "device": "cpu", "allow_network": False},
            "environment": {"type": "pusht", "batch_size": 2},
            "evaluation": {"n_episodes": 2},
            "output": {"root": str(tmp_path / name)},
        }
        path = tmp_path / f"{name}.yaml"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    spec_a = make_spec("spec_a")
    spec_b = make_spec("spec_b")
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        yaml.safe_dump({"specs": [str(spec_a), str(spec_b)]}), encoding="utf-8"
    )

    result = runner.invoke(darwin_app, ["eval", "suite", "--suite", str(suite_path), "--skip-probe"])
    assert result.exit_code == 0, result.output
    assert "Suite Comparison" in result.output
    assert "spec_a" in result.output or "spec_b" in result.output
