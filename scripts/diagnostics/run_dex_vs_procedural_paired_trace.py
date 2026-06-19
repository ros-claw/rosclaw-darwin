#!/usr/bin/env python3
"""Paired trace diff: dex_cube success vs procedural_cube failure.

Runs the same policy on the official dex_cube task and the procedural_cube OOD
task for a shared set of seeds, then compares per-step traces to localise the
first divergence (typically the DESCEND -> GRASP transition).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_abs.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/dex_vs_procedural_paired_trace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paired trace diff for dex vs procedural cube")
    parser.add_argument(
        "--dex-task",
        default="configs/tasks/goal_pose_dex_cube_official.yaml",
        help="Official dex_cube task config",
    )
    parser.add_argument(
        "--procedural-task",
        default="configs/tasks/goal_pose_procedural_cube_ood.yaml",
        help="Procedural cube OOD diagnostic task config",
    )
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Policy config path")
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[0, 1, 2, 3, 4],
        help="Seeds to run for both tasks",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
        help="Output directory for traces and diff report",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill any running Arena containers before starting",
    )
    return parser.parse_args()


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    import subprocess
    import sys

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
    return killed


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in ".-_" else "_" for c in value)


def _run_seed(task_path: str, policy_config: dict, seed: int, out_dir: Path) -> dict[str, Any]:
    task = TaskLoader().load(task_path)
    task_id = task.id
    trace_dir = out_dir / _safe_name(task_id) / f"seed_{seed}" / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)

    task.mutation.seed = seed
    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=1,
        trace_dir=trace_dir,
    )

    summary = {
        "task_id": task_id,
        "seed": seed,
        "status": result.status,
        "metrics": result.metrics,
        "failure_types": result.failure_types,
        "asset_info": result.metadata.get("asset_info"),
        "benchmark_validity": result.metadata.get("benchmark_validity"),
        "leaderboard_excluded": result.leaderboard_excluded,
        "trace_path": str(trace_dir / "episode_trace.jsonl"),
    }
    (out_dir / _safe_name(task_id) / f"seed_{seed}" / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return summary


def _read_trace(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    records = []
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _summarise_trace(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}

    # Aggregate over DESCEND phase.
    descend = [r for r in records if r.get("phase") == "DESCEND"]
    min_z_error = min(
        (r.get("grasp_z_error") for r in descend if r.get("grasp_z_error") is not None),
        default=None,
    )
    min_dist_error = min(
        (r.get("grasp_dist_error") for r in descend if r.get("grasp_dist_error") is not None),
        default=None,
    )

    # Find first GRASP step.
    grasp_step = None
    for i, r in enumerate(records):
        if r.get("phase") == "GRASP":
            grasp_step = i
            break

    # Last object height.
    object_z_final = next(
        (r.get("object_z") for r in reversed(records) if r.get("object_z") is not None),
        None,
    )
    object_z_max = max(
        (r.get("object_z") for r in records if r.get("object_z") is not None),
        default=None,
    )

    return {
        "total_steps": len(records),
        "descend_steps": len(descend),
        "grasp_step": grasp_step,
        "min_grasp_z_error": min_z_error,
        "min_grasp_dist_error": min_dist_error,
        "object_z_final": object_z_final,
        "object_z_max": object_z_max,
        "final_phase": records[-1].get("phase"),
        "phases_reached": sorted(set(r.get("phase") for r in records if r.get("phase"))),
    }


def _compare_seed(dex_summary: dict, proc_summary: dict) -> dict[str, Any]:
    dex_trace = _summarise_trace(_read_trace(Path(dex_summary["trace_path"])))
    proc_trace = _summarise_trace(_read_trace(Path(proc_summary["trace_path"])))

    return {
        "seed": dex_summary["seed"],
        "dex_status": dex_summary["status"],
        "procedural_status": proc_summary["status"],
        "dex_success_rate": dex_summary["metrics"].get("success_rate"),
        "procedural_success_rate": proc_summary["metrics"].get("success_rate"),
        "dex_trace": dex_trace,
        "procedural_trace": proc_trace,
        "divergence": {
            "grasp_step_delta": (
                None
                if dex_trace.get("grasp_step") is None or proc_trace.get("grasp_step") is None
                else proc_trace["grasp_step"] - dex_trace["grasp_step"]
            ),
            "min_grasp_z_error_delta": (
                None
                if dex_trace.get("min_grasp_z_error") is None or proc_trace.get("min_grasp_z_error") is None
                else round(proc_trace["min_grasp_z_error"] - dex_trace["min_grasp_z_error"], 6)
            ),
            "min_grasp_dist_error_delta": (
                None
                if dex_trace.get("min_grasp_dist_error") is None or proc_trace.get("min_grasp_dist_error") is None
                else round(proc_trace["min_grasp_dist_error"] - dex_trace["min_grasp_dist_error"], 6)
            ),
            "object_z_max_delta": (
                None
                if dex_trace.get("object_z_max") is None or proc_trace.get("object_z_max") is None
                else round(proc_trace["object_z_max"] - dex_trace["object_z_max"], 6)
            ),
        },
    }


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.cleanup:
        _cleanup_arena_containers()

    with open(args.policy, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(args.policy).stem)

    dex_summaries: list[dict] = []
    proc_summaries: list[dict] = []

    for seed in args.seeds:
        print(f"\n=== seed {seed}: dex_cube ===")
        dex_summaries.append(_run_seed(args.dex_task, policy_config, seed, args.out_dir))
        print(f"\n=== seed {seed}: procedural_cube ===")
        proc_summaries.append(_run_seed(args.procedural_task, policy_config, seed, args.out_dir))

    comparisons = []
    for dex, proc in zip(dex_summaries, proc_summaries):
        comparisons.append(_compare_seed(dex, proc))

    report = {
        "args": {
            "dex_task": args.dex_task,
            "procedural_task": args.procedural_task,
            "policy": args.policy,
            "seeds": args.seeds,
            "out_dir": str(args.out_dir),
        },
        "comparisons": comparisons,
        "aggregate": {
            "dex_success_rate": sum(1 for c in comparisons if c["dex_success_rate"] == 1.0) / len(comparisons),
            "procedural_success_rate": sum(1 for c in comparisons if c["procedural_success_rate"] == 1.0) / len(comparisons),
            "dex_grasp_reached_rate": sum(1 for c in comparisons if c["dex_trace"].get("grasp_step") is not None) / len(comparisons),
            "procedural_grasp_reached_rate": sum(1 for c in comparisons if c["procedural_trace"].get("grasp_step") is not None) / len(comparisons),
        },
    }

    report_path = args.out_dir / "paired_trace_diff_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nPaired trace diff report written to {report_path}")

    csv_path = args.out_dir / "paired_trace_diff_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed",
            "dex_status",
            "procedural_status",
            "dex_success_rate",
            "procedural_success_rate",
            "dex_grasp_step",
            "procedural_grasp_step",
            "grasp_step_delta",
            "dex_min_grasp_z_error",
            "procedural_min_grasp_z_error",
            "min_grasp_z_error_delta",
            "dex_min_grasp_dist_error",
            "procedural_min_grasp_dist_error",
            "min_grasp_dist_error_delta",
            "dex_object_z_max",
            "procedural_object_z_max",
            "object_z_max_delta",
        ])
        for c in comparisons:
            writer.writerow([
                c["seed"],
                c["dex_status"],
                c["procedural_status"],
                c["dex_success_rate"],
                c["procedural_success_rate"],
                c["dex_trace"].get("grasp_step"),
                c["procedural_trace"].get("grasp_step"),
                c["divergence"]["grasp_step_delta"],
                c["dex_trace"].get("min_grasp_z_error"),
                c["procedural_trace"].get("min_grasp_z_error"),
                c["divergence"]["min_grasp_z_error_delta"],
                c["dex_trace"].get("min_grasp_dist_error"),
                c["procedural_trace"].get("min_grasp_dist_error"),
                c["divergence"]["min_grasp_dist_error_delta"],
                c["dex_trace"].get("object_z_max"),
                c["procedural_trace"].get("object_z_max"),
                c["divergence"]["object_z_max_delta"],
            ])
    print(f"Paired trace diff CSV written to {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
