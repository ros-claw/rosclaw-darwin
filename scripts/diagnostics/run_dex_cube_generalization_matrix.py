#!/usr/bin/env python3
"""Run a randomized goal_pose validation matrix for the official dex_cube asset.

The script sweeps seeds sequentially (one container at a time), records per-seed
metrics, classifies failures, detects physics anomalies, and emits CI-ready
artifacts.  It is intentionally sequential because concurrent Arena Docker runs
still suffer from GPU/container resource contention.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.progress_metrics import (
    classify_failure_class,
    compute_episode_metrics,
    detect_metric_anomaly,
)
from rosclaw_darwin.evaluation.reproducibility import persist_run_artifacts
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/dex_cube_generalization")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run dex_cube goal_pose generalization matrix across seeds"
    )
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Task config path")
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Policy config path")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",
        default=["0:99"],
        help="Seeds to evaluate. Supports ranges like 0:99 and individual seeds like 0 1 2.",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=1,
        help="Episodes per seed",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill any running rosclaw-darwin:arena-base containers before each seed.",
    )
    parser.add_argument(
        "--policy-overrides",
        type=str,
        default=None,
        help='JSON dict of policy_config_dict overrides, e.g. \'{"approach_offset_z": 0.25}\'',
    )
    parser.add_argument(
        "--classify-failures",
        action="store_true",
        help="Classify each failure into one of the v1.6 failure classes.",
    )
    parser.add_argument(
        "--save-traces-on-failure",
        action="store_true",
        help="Always keep trace artifacts for failed seeds.",
    )
    parser.add_argument(
        "--strict-official-asset",
        action="store_true",
        help="Exclude runs that use a procedural fallback or cannot claim the official benchmark.",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Run seeds serially (default). Present for documentation/CI compatibility.",
    )
    return parser.parse_args()


def _parse_seeds(tokens: list[str]) -> list[int]:
    """Expand seed tokens into a sorted list of unique ints."""
    seeds: set[int] = set()
    for token in tokens:
        if ":" in token:
            parts = token.split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid seed range: {token}")
            start, end = int(parts[0]), int(parts[1])
            seeds.update(range(start, end + 1))
        else:
            seeds.add(int(token))
    return sorted(seeds)


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    """Kill any running containers based on the Arena image."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"ancestor={image}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("docker not found; skipping cleanup.", file=sys.stderr)
        return 0
    container_ids = [c for c in result.stdout.strip().splitlines() if c]
    if not container_ids:
        return 0
    print(f"Killing {len(container_ids)} lingering Arena container(s)...", file=sys.stderr)
    killed = 0
    for cid in container_ids:
        kill_result = subprocess.run(
            ["docker", "kill", cid],
            capture_output=True,
            text=True,
            check=False,
        )
        if kill_result.returncode == 0:
            killed += 1
        else:
            print(f"Failed to kill {cid}: {kill_result.stderr.strip()}", file=sys.stderr)
    return killed


def _first_record(trace_path: Path) -> dict[str, Any] | None:
    if not trace_path.exists():
        return None
    try:
        with trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
    except Exception:
        pass
    return None


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


def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    width = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, centre - width), min(1.0, centre + width))


def _bootstrap_ci(
    outcomes: list[bool], n_bootstrap: int = 2000, ci: float = 0.95
) -> tuple[float, float]:
    """Return percentile bootstrap CI for success rate."""
    if not outcomes:
        return (0.0, 1.0)
    n = len(outcomes)
    rates: list[float] = []
    rng = random.Random(42)
    for _ in range(n_bootstrap):
        sample = [rng.choice(outcomes) for _ in range(n)]
        rates.append(sum(sample) / n)
    rates.sort()
    alpha = (1 - ci) / 2
    lo_idx = int(alpha * n_bootstrap)
    hi_idx = int((1 - alpha) * n_bootstrap) - 1
    return (rates[max(0, lo_idx)], rates[min(n_bootstrap - 1, hi_idx)])


def _compute_confidence_intervals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [r.get("success_rate") == 1.0 for r in rows if r.get("success_rate") is not None]
    n = len(outcomes)
    successes = sum(outcomes)
    wilson = _wilson_ci(successes, n)
    bootstrap = _bootstrap_ci(outcomes)
    return {
        "n": n,
        "successes": successes,
        "success_rate": successes / n if n else None,
        "wilson_95_ci": [round(wilson[0], 4), round(wilson[1], 4)],
        "bootstrap_95_ci": [round(bootstrap[0], 4), round(bootstrap[1], 4)],
    }


def _run_seed(
    task_path: str,
    task_yaml: str,
    policy_config: dict[str, Any],
    seed: int,
    episodes: int,
    out_dir: Path,
    cleanup: bool = False,
    classify_failures: bool = False,
    save_traces_on_failure: bool = False,
    strict_official_asset: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed_{seed:03d}"
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

    record: dict[str, Any] = _first_record(trace_path) or {}
    metrics = result.metrics or {}

    # Load full trace and compute host-side episode metrics for classification.
    trace = _load_trace(trace_path)
    episode_metrics = compute_episode_metrics(trace) if trace else {}

    failure_class = "unknown"
    anomaly_tags: list[str] = []
    if classify_failures:
        anomaly, anomaly_tags = detect_metric_anomaly({**metrics, **episode_metrics})
        if anomaly:
            failure_class = "metric_parser_error" if any("nan:" in t for t in anomaly_tags) else "physics_anomaly"
        else:
            combined = {**episode_metrics, **metrics, "object_y_initial": record.get("object_y")}
            failure_class = classify_failure_class(combined, trace=trace)

    asset_fallback_used = bool(metrics.get("asset_info_asset_fallback_used", False))
    can_claim_official = bool(metrics.get("benchmark_validity_can_claim_official_benchmark", True))
    invalid_reason: str | None = None
    if strict_official_asset and (asset_fallback_used or not can_claim_official):
        invalid_reason = "asset_fallback_or_not_official"

    row: dict[str, Any] = {
        "seed": seed,
        "status": result.status,
        "success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "object_height_max_mean": metrics.get("object_height_max_mean"),
        "object_height_delta_mean": metrics.get("object_height_delta_mean"),
        "object_x_initial": record.get("object_x"),
        "object_y_initial": record.get("object_y"),
        "object_z_initial": record.get("object_z"),
        "object_yaw_initial": record.get("object_yaw"),
        "target_yaw": record.get("target_yaw"),
        "object_yaw_error": record.get("object_yaw_error"),
        "eef_to_object_distance_initial_mean": metrics.get("eef_to_object_distance_initial_mean"),
        "eef_to_object_distance_min_mean": metrics.get("eef_to_object_distance_min_mean"),
        "min_grasp_z_error_mean": metrics.get("min_grasp_z_error_mean"),
        "min_grasp_dist_mean": metrics.get("min_grasp_dist_mean"),
        "descend_exit_rate": metrics.get("descend_exit_rate"),
        "grasp_phase_reached_rate": metrics.get("grasp_phase_reached_rate"),
        "lift_phase_reached_rate": metrics.get("lift_phase_reached_rate"),
        "dominant_blocking_reason_distribution_z_not_ok": metrics.get(
            "dominant_blocking_reason_distribution_z_not_ok"
        ),
        "asset_fallback_used": asset_fallback_used,
        "benchmark_validity_can_claim_official_benchmark": can_claim_official,
        "failure_class": failure_class,
        "anomaly_tags": anomaly_tags,
        "invalid_for_official_benchmark": invalid_reason is not None,
        "invalid_reason": invalid_reason,
        "run_id": result.run_id,
    }

    # Persist reproducible run artifacts.
    trace_copy = run_dir / "trace.jsonl"
    if trace_path.exists():
        shutil.copy(trace_path, trace_copy)

    policy_name = Path(policy_config.get("policy_id", "policy")).stem
    stamped = run_dir / f"{policy_name}_seed{seed}_{int(time.time())}.jsonl"
    if trace_path.exists():
        shutil.copy(trace_path, stamped)

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

    asset_info = {
        "asset_fallback_used": asset_fallback_used,
        "can_claim_official_benchmark": can_claim_official,
    }
    (run_dir / "asset_info.json").write_text(json.dumps(asset_info, indent=2))
    (run_dir / "failure_signature.json").write_text(
        json.dumps(
            {
                "failure_class": failure_class,
                "anomaly_tags": anomaly_tags,
                "episode_metrics": episode_metrics,
            },
            indent=2,
            default=str,
        )
    )

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--task", task_path,
        "--policy", policy_config.get("policy_source", "unknown"),
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

    return row


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    valid_rows = [r for r in rows if not r.get("invalid_for_official_benchmark")]
    invalid_rows = [r for r in rows if r.get("invalid_for_official_benchmark")]

    successes = [r for r in valid_rows if r.get("success_rate") == 1.0]
    failed = [r for r in valid_rows if r.get("success_rate") != 1.0]

    def _mean(key: str) -> float | None:
        vals = [r[key] for r in valid_rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def _bin_success(rows_subset: list[dict[str, Any]], key: str, lo: float, hi: float) -> dict[str, Any]:
        binned = [r for r in rows_subset if r.get(key) is not None and lo <= r[key] < hi]
        return {
            "count": len(binned),
            "success_rate": len([r for r in binned if r.get("success_rate") == 1.0]) / len(binned) if binned else None,
        }

    target_yaw_bins = {
        "0_to_0.5": _bin_success(valid_rows, "target_yaw", 0.0, 0.5),
        "0.5_to_1.0": _bin_success(valid_rows, "target_yaw", 0.5, 1.0),
        "1.0_to_1.5": _bin_success(valid_rows, "target_yaw", 1.0, 1.5),
        "1.5_to_2.0": _bin_success(valid_rows, "target_yaw", 1.5, 2.0),
        "2.0_to_2.5": _bin_success(valid_rows, "target_yaw", 2.0, 2.5),
        "2.5_to_pi": _bin_success(valid_rows, "target_yaw", 2.5, 3.15),
    }

    object_yaw_bins = {
        "-0.5_to_0": _bin_success(valid_rows, "object_yaw_initial", -0.5, 0.0),
        "0_to_0.5": _bin_success(valid_rows, "object_yaw_initial", 0.0, 0.5),
    }

    failure_distribution: dict[str, int] = {}
    for r in failed:
        fc = r.get("failure_class") or "unknown"
        failure_distribution[fc] = failure_distribution.get(fc, 0) + 1

    workspace_failure_rate = failure_distribution.get("workspace_unreachable", 0) / len(valid_rows) if valid_rows else None
    approach_collision_rate = failure_distribution.get("approach_collision", 0) / len(valid_rows) if valid_rows else None
    large_yaw_slip_rate = failure_distribution.get("large_yaw_slip", 0) / len(valid_rows) if valid_rows else None
    physics_anomaly_rate = failure_distribution.get("physics_anomaly", 0) / len(valid_rows) if valid_rows else None
    metric_parser_error_rate = failure_distribution.get("metric_parser_error", 0) / len(valid_rows) if valid_rows else None
    orientation_achieved_rate = (
        len([r for r in valid_rows if r.get("success_rate") == 1.0 or r.get("failure_class") != "orientation_not_achieved"])
        / len(valid_rows)
        if valid_rows else None
    )

    return {
        "total_seeds": total,
        "valid_seeds": len(valid_rows),
        "invalid_seeds": len(invalid_rows),
        "successful_seeds": len(successes),
        "failed_seeds": len(failed),
        "overall_success_rate": len(successes) / len(valid_rows) if valid_rows else None,
        "progress_mean": _mean("progress_mean"),
        "object_height_max_mean": _mean("object_height_max_mean"),
        "eef_to_object_distance_initial_mean": _mean("eef_to_object_distance_initial_mean"),
        "eef_to_object_distance_min_mean": _mean("eef_to_object_distance_min_mean"),
        "min_grasp_z_error_mean": _mean("min_grasp_z_error_mean"),
        "min_grasp_dist_mean": _mean("min_grasp_dist_mean"),
        "target_yaw_bin_success": target_yaw_bins,
        "object_yaw_initial_bin_success": object_yaw_bins,
        "failure_distribution": failure_distribution,
        "workspace_failure_rate": workspace_failure_rate,
        "approach_collision_rate": approach_collision_rate,
        "large_yaw_slip_rate": large_yaw_slip_rate,
        "physics_anomaly_rate": physics_anomaly_rate,
        "metric_parser_error_rate": metric_parser_error_rate,
        "orientation_achieved_rate": orientation_achieved_rate,
        "failed_seed_details": [
            {k: r[k] for k in ["seed", "success_rate", "progress_mean", "target_yaw", "object_yaw_initial", "failure_class"]
             if k in r}
            for r in failed
        ],
        "invalid_seed_details": [
            {k: r[k] for k in ["seed", "asset_fallback_used", "benchmark_validity_can_claim_official_benchmark", "invalid_reason"]
             if k in r}
            for r in invalid_rows
        ],
    }


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for row in rows:
            f.write(",".join(str(row.get(k, "")) for k in keys) + "\n")


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_seeds(args.seeds)

    with open(args.policy, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(args.policy).stem)
    policy_config["policy_source"] = args.policy

    if args.policy_overrides:
        overrides = json.loads(args.policy_overrides)
        if overrides:
            policy_config.setdefault("policy_config_dict", {}).update(overrides)
            override_id = "_".join(f"{k}={v}" for k, v in overrides.items())
            policy_config["policy_id"] = f"{policy_config['policy_id']}_{override_id}"

    with open(args.task, "r", encoding="utf-8") as f:
        task_yaml = f.read()

    rows: list[dict[str, Any]] = []
    for seed in seeds:
        print(f"\n=== seed {seed} ===")
        try:
            row = _run_seed(
                args.task,
                task_yaml,
                policy_config,
                seed,
                args.episodes,
                out_dir,
                cleanup=args.cleanup,
                classify_failures=args.classify_failures,
                save_traces_on_failure=args.save_traces_on_failure,
                strict_official_asset=args.strict_official_asset,
            )
        except Exception as exc:
            row = {
                "seed": seed,
                "status": f"error: {exc}",
                "success_rate": None,
                "progress_mean": None,
                "failure_class": "unknown",
            }
        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows)
    summary["seeds"] = seeds
    summary["task"] = args.task
    summary["policy"] = args.policy
    summary["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    per_seed_csv = out_dir / "per_seed_results.csv"
    summary_json = out_dir / "aggregate_summary.json"
    failure_summary_json = out_dir / "failure_summary.json"
    ci_json = out_dir / "confidence_intervals.json"

    _write_csv(rows, per_seed_csv)
    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    with failure_summary_json.open("w", encoding="utf-8") as f:
        json.dump({"failure_distribution": summary["failure_distribution"]}, f, indent=2, default=str)
    with ci_json.open("w", encoding="utf-8") as f:
        json.dump(_compute_confidence_intervals(rows), f, indent=2, default=str)

    print("\n=== aggregate summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"CSV: {per_seed_csv}")
    print(f"JSON: {summary_json}")


if __name__ == "__main__":
    main()
