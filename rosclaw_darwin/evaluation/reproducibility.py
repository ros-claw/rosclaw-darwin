"""Reproducibility helpers: collect run metadata and persist run artifacts.

Every real Arena run should leave behind enough information for the result
to be audited and reproduced.  This module collects git, Docker, environment,
and seed metadata, and writes the standard Darwin run artifact layout.

Standard layout for a persisted run::

    run_dir/
      command.json              -> the command that produced the run
      task.yaml                 -> task specification
      policy.yaml               -> policy configuration
      result.json               -> full EvaluationResult
      summary.json              -> concise metrics + metadata
      episode_metrics.jsonl     -> one line per episode (optional)
      phase_traces.jsonl        -> one line per episode (optional)
      failure_signatures.jsonl  -> one line per episode (optional)
      stdout.log                -> captured stdout (optional)
      stderr.log                -> captured stderr (optional)
      git_info.json             -> commit / branch / dirty flag
      docker_info.json          -> image / container / gpu info
      environment_info.json     -> python / timestamp / hostname
      seed_info.json            -> requested seed and notes
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult


def _run_cmd(cmd: list[str], cwd: Path | str | None = None, timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a subprocess command and return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def collect_git_info(repo_path: Path | str | None = None) -> dict[str, Any]:
    """Collect git metadata for the Darwin repo or ``repo_path``."""
    path = Path(repo_path) if repo_path else Path(__file__).parent.parent.parent
    info: dict[str, Any] = {
        "rosclaw_darwin_commit": None,
        "rosclaw_darwin_branch": None,
        "arena_commit": None,
        "dirty": None,
    }

    rc, commit, _ = _run_cmd(["git", "rev-parse", "HEAD"], cwd=path)
    if rc == 0:
        info["rosclaw_darwin_commit"] = commit

    rc, branch, _ = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    if rc == 0:
        info["rosclaw_darwin_branch"] = branch

    rc, dirty_out, _ = _run_cmd(["git", "status", "--porcelain"], cwd=path)
    if rc == 0:
        info["dirty"] = bool(dirty_out.strip())

    # Arena repo commit, if available.
    arena_repo = os.environ.get("ROSCLAW_ARENA_REPO") or os.environ.get("ARENA_REPO")
    if arena_repo and Path(arena_repo).exists():
        rc, arena_commit, _ = _run_cmd(["git", "rev-parse", "HEAD"], cwd=arena_repo)
        if rc == 0:
            info["arena_commit"] = arena_commit

    return info


def collect_docker_info(image: str = "rosclaw-darwin:arena-base") -> dict[str, Any]:
    """Collect Docker runtime metadata."""
    info: dict[str, Any] = {
        "image": image,
        "image_id": None,
        "container_id": None,
        "docker_version": None,
        "gpu": None,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "nvidia_driver": None,
    }

    rc, version, _ = _run_cmd(["docker", "version", "--format", "{{.Server.Version}}"])
    if rc == 0:
        info["docker_version"] = version

    rc, image_id, _ = _run_cmd(["docker", "images", "--format", "{{.ID}}", image])
    if rc == 0 and image_id:
        info["image_id"] = image_id.splitlines()[0].strip() or None

    # Try nvidia-smi for GPU / driver info.
    rc, smi, _ = _run_cmd(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    if rc == 0 and smi:
        parts = [p.strip() for p in smi.splitlines()[0].split(",")]
        if len(parts) >= 2:
            info["gpu"] = parts[0]
            info["nvidia_driver"] = parts[1]

    return info


def collect_environment_info() -> dict[str, Any]:
    """Collect host Python / timestamp / hostname metadata."""
    return {
        "python_version": platform.python_version(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hostname": platform.node(),
        "isaac_sim_version": os.environ.get("ISAACSIM_VERSION"),
        "isaac_lab_version": os.environ.get("ISAACLAB_VERSION"),
    }


def make_seed_info(
    requested_seed: int | None,
    arena_seed_controlled: bool = False,
    uncontrolled_randomness_notes: str | None = None,
) -> dict[str, Any]:
    """Build a seed metadata record."""
    return {
        "requested_seed": requested_seed,
        "arena_seed_controlled": arena_seed_controlled,
        "uncontrolled_randomness_notes": uncontrolled_randomness_notes,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write a list of dicts as JSON Lines."""
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def persist_run_artifacts(
    run_dir: Path | str,
    result: EvaluationResult,
    task_yaml: str,
    policy_config: dict[str, Any],
    *,
    command: list[str] | None = None,
    seed: int | None = None,
    episode_metrics: list[dict[str, Any]] | None = None,
    phase_traces: list[dict[str, Any]] | None = None,
    failure_signatures: list[dict[str, Any]] | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    docker_image: str = "rosclaw-darwin:arena-base",
    arena_seed_controlled: bool = False,
    uncontrolled_randomness_notes: str | None = None,
) -> dict[str, Path]:
    """Persist a complete, reproducible run artifact directory.

    Returns a mapping of artifact name -> written path.
    """
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)

    summary = {
        "run_id": result.run_id,
        "task_id": result.task_id,
        "policy_id": result.policy_id,
        "adapter": result.adapter,
        "status": result.status,
        "metrics": result.metrics,
        "failure_types": result.failure_types,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "metric_scope": result.metric_scope.value,
        "claim_level": result.claim_level.value,
        "can_claim_capability": result.can_claim_capability,
        "can_claim_evolution": result.can_claim_evolution,
        "leaderboard_excluded": result.leaderboard_excluded,
    }

    artifacts: dict[str, Path] = {}

    # Core artifacts.
    (run_path / "result.json").write_text(result.model_dump_json(indent=2))
    artifacts["result.json"] = run_path / "result.json"

    (run_path / "task.yaml").write_text(task_yaml)
    artifacts["task.yaml"] = run_path / "task.yaml"

    (run_path / "policy.yaml").write_text(json.dumps(policy_config, indent=2))
    artifacts["policy.yaml"] = run_path / "policy.yaml"

    (run_path / "summary.json").write_text(json.dumps(summary, indent=2))
    artifacts["summary.json"] = run_path / "summary.json"

    if command is not None:
        (run_path / "command.json").write_text(json.dumps(command, indent=2))
        artifacts["command.json"] = run_path / "command.json"

    # Optional per-episode artifacts.
    if episode_metrics:
        _write_jsonl(run_path / "episode_metrics.jsonl", episode_metrics)
        artifacts["episode_metrics.jsonl"] = run_path / "episode_metrics.jsonl"
    if phase_traces:
        _write_jsonl(run_path / "phase_traces.jsonl", phase_traces)
        artifacts["phase_traces.jsonl"] = run_path / "phase_traces.jsonl"
    if failure_signatures:
        _write_jsonl(run_path / "failure_signatures.jsonl", failure_signatures)
        artifacts["failure_signatures.jsonl"] = run_path / "failure_signatures.jsonl"

    # Logs.
    if stdout is not None:
        (run_path / "stdout.log").write_text(stdout)
        artifacts["stdout.log"] = run_path / "stdout.log"
    if stderr is not None:
        (run_path / "stderr.log").write_text(stderr)
        artifacts["stderr.log"] = run_path / "stderr.log"

    # Reproducibility metadata.
    (run_path / "git_info.json").write_text(json.dumps(collect_git_info(), indent=2))
    artifacts["git_info.json"] = run_path / "git_info.json"

    (run_path / "docker_info.json").write_text(json.dumps(collect_docker_info(docker_image), indent=2))
    artifacts["docker_info.json"] = run_path / "docker_info.json"

    (run_path / "environment_info.json").write_text(json.dumps(collect_environment_info(), indent=2))
    artifacts["environment_info.json"] = run_path / "environment_info.json"

    seed_info = make_seed_info(
        requested_seed=seed,
        arena_seed_controlled=arena_seed_controlled,
        uncontrolled_randomness_notes=uncontrolled_randomness_notes,
    )
    (run_path / "seed_info.json").write_text(json.dumps(seed_info, indent=2))
    artifacts["seed_info.json"] = run_path / "seed_info.json"

    return artifacts
