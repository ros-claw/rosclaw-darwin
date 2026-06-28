#!/usr/bin/env python3
"""Paired no-regression policy evaluation.

Runs a baseline policy and a candidate policy on the same seeds, classifies
each seed as rescued / newly_failed / unchanged_success / unchanged_failure /
invalid_pair, and emits a paired summary with McNemar test and bootstrap CI.

The script is sequential by default to avoid Arena Docker container contention.
A --mock mode synthesizes deterministic outcomes for schema/IO testing.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Allow the script to be run directly from the repo without an editable install.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yaml  # noqa: E402

from rosclaw_darwin.adapters.arena import ArenaAdapter  # noqa: E402
from rosclaw_darwin.evaluation.paired_evaluation import (  # noqa: E402
    PairedEvaluationResult,
    PairedSeedOutcome,
    compute_paired_summary,
)
from rosclaw_darwin.evaluation.progress_metrics import (  # noqa: E402
    classify_failure_class,
    compute_episode_metrics,
    detect_metric_anomaly,
)
from rosclaw_darwin.evaluation.reproducibility import persist_run_artifacts  # noqa: E402
from rosclaw_darwin.tdl.loader import TaskLoader  # noqa: E402

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_BASELINE = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_CANDIDATE = "configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml"
_DEFAULT_OUT_DIR = Path("data_v20/paired/official_seed24_micro_recovery_0_199")


SEED24_RESCUED = {24, 154, 198}
BASELINE_FAILURES_100_199 = {105, 131, 156, 188}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paired policy evaluation")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--baseline-policy", default=_DEFAULT_BASELINE)
    parser.add_argument("--candidate-policy", default=_DEFAULT_CANDIDATE)
    parser.add_argument("--seeds", type=str, default="0:199")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    parser.add_argument("--strict-official-asset", action="store_true", default=True)
    parser.add_argument("--classify-failures", action="store_true", default=True)
    parser.add_argument("--mock", action="store_true", help="Synthesize outcomes; do not run Docker.")
    parser.add_argument("--mock-failure-type", default="grip_force_insufficient")
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--resume", action="store_true", help="Skip seeds that already have a valid pair_result.json.")
    return parser.parse_args()


def _parse_seeds(text: str) -> list[int]:
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    seeds: set[int] = set()
    for p in parts:
        if ":" in p:
            start, end = p.split(":", 1)
            seeds.update(range(int(start), int(end) + 1))
        else:
            seeds.add(int(p))
    return sorted(seeds)


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"ancestor={image}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 0
    container_ids = [c for c in result.stdout.strip().splitlines() if c]
    killed = 0
    for cid in container_ids:
        kill_result = subprocess.run(
            ["docker", "kill", cid], capture_output=True, text=True, check=False
        )
        if kill_result.returncode == 0:
            killed += 1
    return killed


def _load_trace(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return records


def _first_record(trace_path: Path) -> dict[str, Any] | None:
    records = _load_trace(trace_path)
    return records[0] if records else None


def _run_single_policy(
    task_path: str,
    task_yaml: str,
    policy_config: dict[str, Any],
    seed: int,
    episodes: int,
    run_dir: Path,
    cleanup: bool = False,
    classify_failures: bool = False,
    strict_official_asset: bool = False,
) -> dict[str, Any]:
    """Run one policy on one seed and return a compact result dict."""
    if cleanup:
        _cleanup_arena_containers()
        # Allow killed containers to fully terminate and release GPU/host memory
        # before launching the next run, preventing startup OOM kills.
        time.sleep(15)

    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=episodes,
        max_steps=None,
        trace_dir=trace_dir,
    )

    metrics = result.metrics or {}
    trace = _load_trace(trace_path)
    episode_metrics = compute_episode_metrics(trace) if trace else {}

    # Infrastructure failures (e.g. HDF5 locking, Python tracebacks) are not
    # policy outcomes.  Flag them so the paired evaluator treats the run as an
    # invalid pair rather than classifying a bogus failure type.
    infra_failure = bool(result.metadata.get("infrastructure_failure"))
    infra_signals = result.metadata.get("infrastructure_signals") or []
    runner_failed = result.status != "completed"

    failure_class = "unknown"
    anomaly_tags: list[str] = []
    if runner_failed or infra_failure:
        failure_class = "infrastructure_failure"
        if infra_signals:
            anomaly_tags.append(f"infrastructure:{','.join(infra_signals)}")
        else:
            anomaly_tags.append(f"runner_status:{result.status}")
    elif classify_failures:
        anomaly, anomaly_tags = detect_metric_anomaly({**metrics, **episode_metrics})
        if anomaly:
            failure_class = "metric_parser_error" if any("nan:" in t for t in anomaly_tags) else "physics_anomaly"
        else:
            record = _first_record(trace_path) or {}
            combined = {**episode_metrics, **metrics, "object_y_initial": record.get("object_y")}
            failure_class = classify_failure_class(combined, trace=trace)

    asset_fallback_used = bool(metrics.get("asset_info_asset_fallback_used", False))
    can_claim_official = bool(metrics.get("benchmark_validity_can_claim_official_benchmark", True))
    notes: list[str] = []
    if strict_official_asset and (asset_fallback_used or not can_claim_official):
        notes.append("invalid_pair")
        notes.append("asset_fallback_or_not_official")
    if anomaly_tags:
        notes.append("invalid_pair")
        notes.append("physics_anomaly" if any(t.startswith("physics_anomaly") for t in anomaly_tags) else "infrastructure_failure")
    if runner_failed or infra_failure:
        notes.append("invalid_pair")
        notes.append(f"runner_status: {result.status}")
        if infra_signals:
            notes.append(f"infrastructure_signals: {','.join(infra_signals)}")

    # Persist reproducible artifacts.
    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    stdout = None
    stderr = None
    if result.stdout_path and Path(result.stdout_path).exists():
        try:
            stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if result.stderr_path and Path(result.stderr_path).exists():
        try:
            stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    policy_name = Path(policy_config.get("policy_id", "policy")).stem
    (run_dir / "asset_info.json").write_text(
        json.dumps(
            {
                "asset_fallback_used": asset_fallback_used,
                "can_claim_official_benchmark": can_claim_official,
            },
            indent=2,
        )
    )
    (run_dir / "failure_signature.json").write_text(
        json.dumps(
            {"failure_class": failure_class, "anomaly_tags": anomaly_tags, "episode_metrics": episode_metrics},
            indent=2,
            default=str,
        )
    )

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--task", task_path,
        "--baseline-policy", policy_config.get("policy_source", "unknown"),
        "--seeds", str(seed),
    ]
    persist_run_artifacts(
        run_dir,
        result,
        task_yaml=task_yaml,
        policy_config=policy_config,
        command=command,
        seed=seed,
        episode_metrics=[episode_metrics] if episode_metrics else None,
        stdout=stdout,
        stderr=stderr,
        arena_seed_controlled=True,
        uncontrolled_randomness_notes="Arena placement seed forwarded via ROSCLAW_ARENA_PLACEMENT_SEED",
    )

    return {
        "seed": seed,
        "policy": policy_name,
        "status": result.status,
        "success": metrics.get("success_rate") == 1.0,
        "success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "failure_class": failure_class,
        "anomaly_tags": anomaly_tags,
        "asset_fallback_used": asset_fallback_used,
        "can_claim_official_benchmark": can_claim_official,
        "notes": notes,
        "artifact_dir": str(run_dir.resolve()),
    }


def _mock_run_single_policy(
    policy_config: dict[str, Any],
    seed: int,
    run_dir: Path,
    failure_type: str = "grip_force_insufficient",
) -> dict[str, Any]:
    """Synthetic run for schema/IO testing without Docker."""
    run_dir.mkdir(parents=True, exist_ok=True)
    policy_name = Path(policy_config.get("policy_id", "policy")).stem
    is_baseline = "reachability_promoted" in policy_name or "baseline" in policy_name

    # Baseline: fails on seed 24 and on the four known 100:199 fragility seeds.
    # Candidate: rescues seed24-like failures; does not change other outcomes.
    if is_baseline:
        success = seed not in ({24} | BASELINE_FAILURES_100_199)
        fc = None if success else failure_type
    else:
        success = seed not in BASELINE_FAILURES_100_199
        fc = None if success else failure_type

    notes: list[str] = []
    (run_dir / "asset_info.json").write_text(
        json.dumps({"asset_fallback_used": False, "can_claim_official_benchmark": True}, indent=2)
    )
    (run_dir / "failure_signature.json").write_text(
        json.dumps({"failure_class": fc or "none", "anomaly_tags": []}, indent=2)
    )

    return {
        "seed": seed,
        "policy": policy_name,
        "status": "mock_completed",
        "success": success,
        "success_rate": 1.0 if success else 0.0,
        "progress_mean": 1.0 if success else 0.5,
        "failure_class": fc or "none",
        "anomaly_tags": [],
        "asset_fallback_used": False,
        "can_claim_official_benchmark": True,
        "notes": notes,
        "artifact_dir": str(run_dir.resolve()),
    }


def _load_policy_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(path).stem)
    policy_config["policy_source"] = path
    return policy_config


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in keys})


def _try_load_existing_pair(seed_dir: Path) -> PairedSeedOutcome | None:
    """Load a previously computed pair result for resume support."""
    pair_path = seed_dir / "pair_result.json"
    if not pair_path.exists():
        return None
    try:
        data = json.loads(pair_path.read_text(encoding="utf-8"))
        pair = PairedSeedOutcome.model_validate(data)
        # Do not resume over runner errors; allow a re-run.
        if any("runner_error" in note for note in pair.notes):
            return None
        # Also re-run pairs where a runner status note indicates a container
        # failure (baseline or candidate did not report "completed"). These are
        # infrastructure failures, not policy outcomes, so we must retry them.
        for note in pair.notes:
            if note.startswith("runner_status:"):
                if "=failed" in note or "=error" in note or "=killed" in note:
                    return None
        return pair
    except Exception:
        return None


def _run_paired_seed(
    task_path: str,
    task_yaml: str,
    baseline_config: dict[str, Any],
    candidate_config: dict[str, Any],
    seed: int,
    episodes: int,
    out_dir: Path,
    cleanup: bool = False,
    classify_failures: bool = False,
    strict_official_asset: bool = False,
    mock: bool = False,
    mock_failure_type: str = "grip_force_insufficient",
) -> tuple[PairedSeedOutcome, dict[str, Any], dict[str, Any]]:
    seed_dir = out_dir / f"seed_{seed:03d}"
    baseline_dir = seed_dir / "baseline"
    candidate_dir = seed_dir / "candidate"

    if mock:
        baseline_result = _mock_run_single_policy(baseline_config, seed, baseline_dir, mock_failure_type)
        candidate_result = _mock_run_single_policy(candidate_config, seed, candidate_dir, mock_failure_type)
    else:
        baseline_result = _run_single_policy(
            task_path,
            task_yaml,
            baseline_config,
            seed,
            episodes,
            baseline_dir,
            cleanup=cleanup,
            classify_failures=classify_failures,
            strict_official_asset=strict_official_asset,
        )
        # Brief pause to let the baseline container fully terminate and release
        # GPU/host memory before the candidate container starts.  Without this,
        # the candidate can be OOM-killed during startup on a busy host.
        time.sleep(20)
        candidate_result = _run_single_policy(
            task_path,
            task_yaml,
            candidate_config,
            seed,
            episodes,
            candidate_dir,
            cleanup=cleanup,
            classify_failures=classify_failures,
            strict_official_asset=strict_official_asset,
        )

    notes = list(baseline_result["notes"]) + list(candidate_result["notes"])
    if baseline_result.get("asset_fallback_used") or candidate_result.get("asset_fallback_used"):
        notes.append("invalid_pair")
    if baseline_result.get("anomaly_tags") or candidate_result.get("anomaly_tags"):
        notes.append("invalid_pair")
    # Treat any non-completed runner status as an invalid pair; runner failures
    # are not policy outcomes and must not be counted as regressions.  Mock runs
    # report "mock_completed" and are treated as valid for schema/IO tests.
    _valid_runner_statuses = {"completed", "mock_completed"}
    baseline_status = baseline_result.get("status", "")
    candidate_status = candidate_result.get("status", "")
    if baseline_status not in _valid_runner_statuses or candidate_status not in _valid_runner_statuses:
        notes.append("invalid_pair")
        notes.append(f"runner_status: baseline={baseline_status}, candidate={candidate_status}")

    pair = PairedSeedOutcome(
        seed=seed,
        baseline_success=baseline_result["success"],
        candidate_success=candidate_result["success"],
        baseline_failure_type=baseline_result.get("failure_class") or None,
        candidate_failure_type=candidate_result.get("failure_class") or None,
        baseline_artifact_dir=baseline_result["artifact_dir"],
        candidate_artifact_dir=candidate_result["artifact_dir"],
        notes=sorted(set(notes)),
    )

    (seed_dir / "pair_result.json").write_text(
        json.dumps(pair.model_dump(), indent=2, default=str)
    )
    return pair, baseline_result, candidate_result


def main() -> int:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cleanup = args.cleanup and not args.no_cleanup

    baseline_config = _load_policy_config(args.baseline_policy)
    candidate_config = _load_policy_config(args.candidate_policy)

    with open(args.task, "r", encoding="utf-8") as f:
        task_yaml = f.read()

    seeds = _parse_seeds(args.seeds)
    outcomes: list[PairedSeedOutcome] = []
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    for seed in seeds:
        print(f"\n=== paired seed {seed} ===", file=sys.stderr)
        seed_dir = out_dir / f"seed_{seed:03d}"
        if args.resume:
            existing = _try_load_existing_pair(seed_dir)
            if existing is not None:
                print(f"Resuming seed {seed} from existing pair_result.json", file=sys.stderr)
                outcomes.append(existing)
                baseline_rows.append({"seed": seed, "status": "resumed", "success": existing.baseline_success})
                candidate_rows.append({"seed": seed, "status": "resumed", "success": existing.candidate_success})
                print(json.dumps(existing.model_dump(), indent=2, default=str))
                continue
        try:
            pair, baseline_row, candidate_row = _run_paired_seed(
                args.task,
                task_yaml,
                baseline_config,
                candidate_config,
                seed,
                args.episodes,
                out_dir,
                cleanup=cleanup,
                classify_failures=args.classify_failures,
                strict_official_asset=args.strict_official_asset,
                mock=args.mock,
                mock_failure_type=args.mock_failure_type,
            )
        except Exception as exc:
            pair = PairedSeedOutcome(
                seed=seed,
                baseline_success=False,
                candidate_success=False,
                baseline_failure_type="runner_error",
                candidate_failure_type="runner_error",
                baseline_artifact_dir=str(out_dir / f"seed_{seed:03d}" / "baseline"),
                candidate_artifact_dir=str(out_dir / f"seed_{seed:03d}" / "candidate"),
                notes=["invalid_pair", f"runner_error: {exc}"],
            )
            baseline_row = {"seed": seed, "status": f"error: {exc}", "success": False}
            candidate_row = {"seed": seed, "status": f"error: {exc}", "success": False}
        outcomes.append(pair)
        baseline_rows.append(baseline_row)
        candidate_rows.append(candidate_row)
        print(json.dumps(pair.model_dump(), indent=2, default=str))

    summary = compute_paired_summary(
        outcomes,
        task_id=out_dir.name,
        baseline_policy=baseline_config.get("policy_id", "baseline"),
        candidate_policy=candidate_config.get("policy_id", "candidate"),
        seed_range=args.seeds,
    )
    result = PairedEvaluationResult(summary=summary, outcomes=outcomes)

    # Write aggregate artifacts.
    (out_dir / "paired_summary.json").write_text(
        json.dumps(result.model_dump(), indent=2, default=str)
    )
    (out_dir / "summary_only.json").write_text(
        json.dumps(summary.model_dump(), indent=2, default=str)
    )
    _write_csv(
        [o.model_dump() for o in outcomes],
        out_dir / "paired_outcomes.csv",
    )

    def _seed_list(predicate):
        return [o.seed for o in outcomes if predicate(o)]

    (out_dir / "rescued_seeds.json").write_text(
        json.dumps(_seed_list(lambda o: o.delta_class == "rescued"), indent=2)
    )
    (out_dir / "newly_failed_seeds.json").write_text(
        json.dumps(_seed_list(lambda o: o.delta_class == "newly_failed"), indent=2)
    )
    (out_dir / "unchanged_failure_seeds.json").write_text(
        json.dumps(_seed_list(lambda o: o.delta_class == "unchanged_failure"), indent=2)
    )
    (out_dir / "invalid_pairs.json").write_text(
        json.dumps(_seed_list(lambda o: o.delta_class == "invalid_pair"), indent=2)
    )

    _write_csv(baseline_rows, out_dir / "baseline_per_seed.csv")
    _write_csv(candidate_rows, out_dir / "candidate_per_seed.csv")

    print("\n=== paired evaluation summary ===")
    print(json.dumps(summary.model_dump(), indent=2, default=str))
    print(f"Output directory: {out_dir}")

    # Return non-zero if the candidate introduced regressions.
    if summary.newly_failed_count > 0:
        print("FAIL: candidate introduced newly_failed seeds.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
