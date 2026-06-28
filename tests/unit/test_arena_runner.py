"""Unit tests for ArenaRunner infrastructure-failure detection and Docker mounts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rosclaw_darwin.evaluation.arena_runner import ArenaRunner


def _make_completed_process(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_detect_infrastructure_failure_blocking_io():
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "/isaac-sim/.../h5py/_hl/files.py", line 555, in __init__\n'
        "BlockingIOError: [Errno 11] Unable to synchronously create file\n"
    )
    failed, signals = ArenaRunner._detect_infrastructure_failure(stderr)
    assert failed is True
    assert "blocking_io_error" in signals
    assert "python_traceback" in signals


def test_detect_infrastructure_failure_physx_warning_ignored():
    stderr = (
        "[Error] [omni.physx.tensors.plugin] "
        "Failed to get a valid attached USD stage id from PhysX simulation\n"
    )
    failed, signals = ArenaRunner._detect_infrastructure_failure(stderr)
    assert failed is False
    assert signals == []


def test_detect_infrastructure_failure_ignores_clean_stderr():
    stderr = "[isaaclab-arena] AppLauncher initialization complete (12.3s)\n"
    failed, signals = ArenaRunner._detect_infrastructure_failure(stderr)
    assert failed is False
    assert signals == []


def test_detect_infrastructure_failure_empty_stderr():
    failed, signals = ArenaRunner._detect_infrastructure_failure("")
    assert failed is False
    assert signals == []


def test_detect_infrastructure_failure_no_space_left():
    stderr = "OSError: [Errno 28] No space left on device: '/tmp/trace.jsonl'\n"
    failed, signals = ArenaRunner._detect_infrastructure_failure(stderr)
    assert failed is True
    assert "no_space_left" in signals


def test_detect_infrastructure_failure_cuda_oom():
    stderr = "RuntimeError: CUDA out of memory: Tried to allocate 2.00 GiB\n"
    failed, signals = ArenaRunner._detect_infrastructure_failure(stderr)
    assert failed is True
    assert "cuda_oom" in signals


def test_run_docker_mounts_residual_and_trigger_models(tmp_path):
    """Residual and trigger model weights are bind-mounted at host-absolute paths."""
    residual_path = tmp_path / "bounded_residual_policy" / "model.json"
    trigger_path = tmp_path / "trigger_model" / "model.json"
    residual_path.parent.mkdir(parents=True)
    trigger_path.parent.mkdir(parents=True)
    residual_path.write_text("{}")
    trigger_path.write_text("{}")

    job = {
        "policy_config_dict": {
            "residual_policy": "triggered_bounded_learned",
            "residual_policy_path": str(residual_path),
            "trigger_model_path": str(trigger_path),
        },
        "timeout_seconds": 5,
    }

    runner = ArenaRunner()
    stdout = "<<<ROSCLAW_ARENA_METRICS>>>{}<<<ROSCLAW_ARENA_METRICS>>>"
    proc = _make_completed_process(returncode=0, stdout=stdout, stderr="")

    with patch("rosclaw_darwin.evaluation.arena_runner.subprocess.run", return_value=proc) as mock_run:
        result = runner._run_docker(
            job,
            run_id="test_run",
            task_id="goal_pose",
            policy_id="triggered_learned",
            started_at="2026-06-27T00:00:00Z",
        )

    assert result.status == "completed"
    cmd = mock_run.call_args[0][0]
    residual_mount = f"{residual_path}:{residual_path}"
    trigger_mount = f"{trigger_path}:{trigger_path}"
    assert residual_mount in cmd
    assert trigger_mount in cmd
    overlay_mount = next((arg for arg in cmd if arg.endswith(":/workspace/data/rosclaw_darwin")), None)
    assert overlay_mount is not None


def test_run_docker_missing_model_path_logs_warning(tmp_path, capfd):
    """Missing model paths are skipped with a warning rather than crashing."""
    residual_path = tmp_path / "missing_residual.json"
    job = {
        "policy_config_dict": {
            "residual_policy_path": str(residual_path),
        },
        "timeout_seconds": 5,
    }

    runner = ArenaRunner()
    stdout = "<<<ROSCLAW_ARENA_METRICS>>>{}<<<ROSCLAW_ARENA_METRICS>>>"
    proc = _make_completed_process(returncode=0, stdout=stdout, stderr="")

    with patch("rosclaw_darwin.evaluation.arena_runner.subprocess.run", return_value=proc):
        runner._run_docker(
            job,
            run_id="test_run",
            task_id="goal_pose",
            policy_id="triggered_learned",
            started_at="2026-06-27T00:00:00Z",
        )

    captured = capfd.readouterr()
    assert "residual_policy_path references a missing file" in captured.out
