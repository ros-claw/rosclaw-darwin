#!/usr/bin/env python3
"""Run a sequential multi-seed goal_pose validation sweep with isolated traces.

Each seed is executed in its own subprocess and gets a private trace directory
so that concurrent Docker containers cannot race on ``episode_trace.jsonl``.
This wrapper intentionally runs seeds one-at-a-time to avoid GPU/container
interference observed when multiple Arena containers are active simultaneously.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

_DEFAULT_TASK = "configs/tasks/goal_pose.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_abs.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/seed_sweeps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sequential multi-seed goal_pose validation sweep"
    )
    parser.add_argument("--start", type=int, default=0, help="First seed (inclusive)")
    parser.add_argument("--end", type=int, default=19, help="Last seed (inclusive)")
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Task config path")
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Policy config path")
    parser.add_argument(
        "--embodiment",
        type=str,
        default=None,
        help="Override Arena embodiment (e.g. franka_ik_abs).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
        help="Output directory for per-seed results and summary.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill any running rosclaw-darwin:arena-base containers before starting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run without executing them.",
    )
    return parser.parse_args()


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


def _run_seed(
    seed: int,
    args: argparse.Namespace,
    sweep_dir: Path,
) -> dict:
    """Run a single seed via run_goal_pose_trace.py and return its summary."""
    seed_out_dir = sweep_dir / f"seed_{seed:02d}"
    seed_out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "scripts/diagnostics/run_goal_pose_trace.py",
        "--task", args.task,
        "--policy", args.policy,
        "--out-dir", str(seed_out_dir),
        "--seed", str(seed),
    ]
    if args.embodiment is not None:
        cmd.extend(["--embodiment", args.embodiment])

    if args.dry_run:
        print(" ".join(cmd))
        return {
            "seed": seed,
            "status": "dry_run",
            "metrics": {},
            "failure_types": {},
        }

    started_at = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "seed": seed,
            "status": "timeout",
            "metrics": {},
            "failure_types": {"timeout": 1},
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "elapsed_seconds": 1800.0,
        }
    elapsed = time.time() - started_at

    # The last line of stdout should be the JSON summary from run_goal_pose_trace.py.
    summary: dict = {"seed": seed, "status": "failed", "metrics": {}, "failure_types": {}}
    marker = "<<<ROSCLAW_SEED_SUMMARY>>>"
    if marker in result.stdout:
        parts = result.stdout.split(marker)
        if len(parts) >= 3:
            try:
                parsed = json.loads(parts[1].strip())
                if isinstance(parsed, dict) and "status" in parsed:
                    summary = parsed
            except json.JSONDecodeError:
                pass
    else:
        # Fallback for older single-line JSON output.
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict) and "status" in parsed:
                        summary = parsed
                        break
                except json.JSONDecodeError:
                    continue

    summary["seed"] = seed
    summary["return_code"] = result.returncode
    summary["elapsed_seconds"] = round(elapsed, 2)
    summary["stdout"] = result.stdout
    summary["stderr"] = result.stderr

    # Persist the parsed summary for this seed.
    (seed_out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return summary


def main() -> int:
    args = parse_args()
    if args.start > args.end:
        print("--start must be <= --end", file=sys.stderr)
        return 1

    sweep_dir = args.out_dir / f"sweep_{time.strftime('%Y-%m-%d_%H%M%S')}"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    print(f"Sweep output directory: {sweep_dir}")

    if args.cleanup:
        _cleanup_arena_containers()

    if args.dry_run:
        print("Dry-run commands:")

    seeds = list(range(args.start, args.end + 1))
    results: list[dict] = []
    for seed in seeds:
        print(f"\n=== seed {seed} ===")
        summary = _run_seed(seed, args, sweep_dir)
        results.append(summary)
        print(json.dumps(summary, indent=2, default=str))

    if args.dry_run:
        return 0

    # Aggregate summary.
    successes = sum(
        1 for r in results
        if r.get("status") == "completed" and r.get("metrics", {}).get("success_rate", 0.0) >= 1.0
    )
    aggregate = {
        "seeds": seeds,
        "num_seeds": len(seeds),
        "successes": successes,
        "success_rate": round(successes / len(seeds), 4) if seeds else 0.0,
        "per_seed": results,
    }

    aggregate_path = sweep_dir / "aggregate_summary.json"
    aggregate_path.write_text(json.dumps(aggregate, indent=2, default=str), encoding="utf-8")
    print(f"\nAggregate summary written to {aggregate_path}")

    csv_path = sweep_dir / "per_seed_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed", "status", "success_rate", "progress",
            "eef_to_object_distance_initial", "object_height_delta",
            "failure_type", "elapsed_seconds",
        ])
        for r in results:
            metrics = r.get("metrics", {})
            failure_types = r.get("failure_types", {})
            failure_type = ",".join(failure_types.keys()) if failure_types else ""
            writer.writerow([
                r["seed"],
                r.get("status", ""),
                metrics.get("success_rate", ""),
                metrics.get("progress", ""),
                metrics.get("eef_to_object_distance_initial_mean", ""),
                metrics.get("object_height_delta_mean", ""),
                failure_type,
                r.get("elapsed_seconds", ""),
            ])
    print(f"Per-seed CSV written to {csv_path}")

    print(f"\n=== RESULT: {successes}/{len(seeds)} seeds succeeded ===")
    return 0 if successes == len(seeds) else 1


if __name__ == "__main__":
    sys.exit(main())
