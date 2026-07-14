"""Optional real LeRobot PushT smoke integration test.

Set ``ROSCLAW_DARWIN_REAL_LEROBOT_EVAL=1`` and register a runtime named
``lerobot_default`` before running. The test is skipped when the runtime or the
environment variable is missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from rosclaw_darwin.cli.darwin_app import darwin_app
from rosclaw_darwin.evaluation.runtime import get_runtime

try:
    from typer.testing import CliRunner
except Exception:  # pragma: no cover
    CliRunner = None


pytestmark = pytest.mark.skipif(
    not os.environ.get("ROSCLAW_DARWIN_REAL_LEROBOT_EVAL")
    or CliRunner is None,
    reason="Set ROSCLAW_DARWIN_REAL_LEROBOT_EVAL=1 to run real LeRobot smoke",
)


def _pusht_spec_path(tmp_path: Path) -> Path:
    spec = {
        "schema_version": "rosclaw.darwin.eval_spec.v1",
        "id": "pusht_real_smoke",
        "backend": "lerobot_eval",
        "runtime": "lerobot_default",
        "policy": {
            "path": "lerobot/diffusion_pusht",
            "device": "cuda",
            "allow_network": True,
            "use_amp": False,
        },
        "environment": {"type": "pusht", "batch_size": 2},
        "evaluation": {"n_episodes": 2, "start_seed": 42, "timeout_sec": 600},
        "output": {"root": str(tmp_path / "eval_runs")},
        "validity_gates": {"require_expected_episode_count": True},
        "performance_gates": {},
    }
    path = tmp_path / "pusht_smoke.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    return path


def test_real_lerobot_runtime_is_registered() -> None:
    """The required runtime must be registered."""
    try:
        rt = get_runtime("lerobot_default")
    except KeyError as exc:
        raise pytest.fail(f"Runtime 'lerobot_default' not registered: {exc}")
    assert rt.mode == "external"
    assert rt.python or rt.image


def test_real_pusht_doctor_passes(tmp_path: Path) -> None:
    runner = CliRunner()
    spec_path = _pusht_spec_path(tmp_path)
    result = runner.invoke(
        darwin_app, ["eval", "doctor", "--runtime", "lerobot_default", "--spec", str(spec_path)]
    )
    assert result.exit_code == 0, result.output


def test_real_pusht_run_produces_valid_evidence(tmp_path: Path) -> None:
    runner = CliRunner()
    spec_path = _pusht_spec_path(tmp_path)
    result = runner.invoke(darwin_app, ["eval", "run", "--spec", str(spec_path)])
    assert result.exit_code == 0, result.output

    # Locate the most recent run directory.
    runs_root = tmp_path / "eval_runs"
    run_dirs = sorted(d for d in runs_root.iterdir() if d.is_dir())
    assert run_dirs, f"No run directories under {runs_root}"
    run_dir = run_dirs[-1]

    validate = runner.invoke(darwin_app, ["eval", "validate", str(run_dir)])
    assert validate.exit_code == 0, validate.output

    assert (run_dir / "manifest.yaml").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "hashes.json").exists()
    assert (run_dir / "checks" / "preflight.json").exists()
    assert (run_dir / "checks" / "validity_gate.json").exists()
    assert (run_dir / "checks" / "performance_gate.json").exists()
    assert (run_dir / "normalized" / "evaluation_result.json").exists()

    result_data = yaml.safe_load(
        (run_dir / "normalized" / "evaluation_result.json").read_text(encoding="utf-8")
    )
    assert result_data["status"] == "completed"
    assert result_data["validity_gate"]["status"] == "passed"
    assert result_data["num_episodes"] == 2
