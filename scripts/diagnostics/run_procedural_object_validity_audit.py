#!/usr/bin/env python3
"""Procedural-cube OOD object validity audit runner.

Runs a passive diagnostic policy for a small number of steps and records:
- object root pose / velocity / quaternion
- bounding box
- rigid body / collision flags
- mass / friction
- metric/policy/trace object index consistency
- table contact / penetration

The goal is to determine whether the procedural fallback is a valid interactive
rigid body before any OOD skill evaluation is attempted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.object_validity import ObjectValidityReport, check_object_validity
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASKS = [
    "configs/tasks/goal_pose_procedural_cube_ood.yaml",
    "configs/tasks/goal_pose_procedural_cube_dex_size.yaml",
    "configs/tasks/goal_pose_procedural_cube_large.yaml",
]
_DEFAULT_OUT_DIR = Path("data_v17/diagnostics/procedural_object_validity_audit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit procedural OOD object validity before skill evaluation"
    )
    parser.add_argument(
        "--tasks",
        type=str,
        nargs="+",
        default=_DEFAULT_TASKS,
        help="Procedural task configs to audit",
    )
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",        default=["0:9"],
        help="Seeds to audit (supports ranges like 0:9)",
    )
    parser.add_argument("--audit-steps", type=int, default=11)
    parser.add_argument("--table-z", type=float, default=0.18)
    parser.add_argument(
        "--episodes-per-run",
        type=int,
        default=1,
        help="Run this many episodes (seeds) in a single Arena container.  When >1, the trace is appended across episodes.",
    )
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    return parser.parse_args()


def _parse_seeds(tokens: list[str]) -> list[int]:
    seeds: set[int] = set()
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if ":" in part:
                start, end = part.split(":")
                seeds.update(range(int(start), int(end) + 1))
            else:
                seeds.add(int(part))
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
    if not container_ids:
        return 0
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


def _record_to_report(task_id: str, seed: int, record: dict[str, Any], table_z: float = 0.18) -> ObjectValidityReport:
    """Convert an audit trace record into an ObjectValidityReport."""
    pos = record.get("object_root_pos") or [record.get("object_x"), record.get("object_y"), record.get("object_z")]
    pos = [float(v) if v is not None else 0.0 for v in pos]
    quat = record.get("object_root_quat") or [0.0, 0.0, 0.0, 1.0]
    quat = [float(v) if v is not None else 0.0 for v in quat]
    bbox = record.get("bbox_extent") or [0.0, 0.0, 0.0]
    bbox = [float(v) if v is not None else 0.0 for v in bbox]
    return check_object_validity(
        ObjectValidityReport(
            task_id=task_id,
            object_name=record.get("object_name", "unknown"),
            object_root_pos=pos,
            object_root_quat=quat,
            bbox_extent=bbox,
            bbox_world_min=record.get("bbox_world_min") or [0.0, 0.0, 0.0],
            bbox_world_max=record.get("bbox_world_max") or [0.0, 0.0, 0.0],
            rigid_body_enabled=bool(record.get("rigid_body_enabled", False)),
            collision_enabled=bool(record.get("collision_enabled", False)),
            table_contact_valid=bool(record.get("object_above_table", False)),
            object_index_consistent=(
                len({record.get("policy_object_index"), record.get("metric_object_index"), record.get("trace_object_index")})
                <= 1
            ),
            object_above_table=bool(record.get("object_above_table", False)),
            linear_velocity=record.get("object_linear_velocity") or [0.0, 0.0, 0.0],
            angular_velocity=record.get("object_angular_velocity") or [0.0, 0.0, 0.0],
            mass=record.get("mass"),
            static_friction=record.get("static_friction"),
            dynamic_friction=record.get("dynamic_friction"),
            requested_object=record.get("requested_object", "unknown"),
            loaded_object=record.get("loaded_object", record.get("object_name", "unknown")),
            metric_object_index=record.get("metric_object_index"),
            policy_object_index=record.get("policy_object_index"),
            trace_object_index=record.get("trace_object_index"),
            step=record.get("step", 0),
            seed=seed,
        ),
        table_z=table_z,
    )


def _run_audit(
    task_path: str,
    task_yaml: str,
    seed: int,
    audit_steps: int,
    table_z: float,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed
    task.metadata.setdefault("asset_policy", {})
    task.metadata["asset_policy"]["allow_procedural_fallback"] = True
    task.metadata["asset_policy"]["require_official_asset"] = False
    task.metadata["asset_policy"]["diagnostic_variant"] = True

    run_dir = out_dir / task.id / f"seed_{seed:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    policy_config = {
        "policy_id": "object_validity_audit",
        "type": "object_validity_audit",
        "policy_type": "object_validity_audit",
        "policy_config_dict": {
            "audit_steps": audit_steps,
            "table_z": table_z,
        },
        "skill_hints": [],
    }

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=None,
        max_steps=audit_steps,
        trace_dir=trace_dir,
    )

    records = _load_trace(trace_path)
    reports = [_record_to_report(task.id, seed, r, table_z=table_z) for r in records if r.get("audit")]

    # Persist trace copy and reports.
    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")
    for report in reports:
        (run_dir / f"object_validity_step_{report.step}.json").write_text(
            report.model_dump_json(indent=2)
        )

    asset_info = (result.metadata or {}).get("asset_info", {})
    benchmark_validity = (result.metadata or {}).get("benchmark_validity", {})

    return {
        "task_id": task.id,
        "task_path": task_path,
        "seed": seed,
        "status": result.status,
        "audit_records": len(reports),
        "object_validity": [r.model_dump() for r in reports],
        "asset_info": asset_info,
        "benchmark_validity": benchmark_validity,
    }


def _run_audit_batch(
    task_path: str,
    task_yaml: str,
    chunk_start_seed: int,
    episodes: int,
    audit_steps: int,
    table_z: float,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    """Run ``episodes`` validity audits in a single Arena container.

    The audit policy appends trace records across episode resets so we can
    amortize container startup time over many seeds.  The loaded object's
    initial conditions vary because the environment RNG advances each reset.
    """
    if cleanup:
        _cleanup_arena_containers()

    task = TaskLoader().load(task_path)
    task.mutation.seed = chunk_start_seed
    task.metadata.setdefault("asset_policy", {})
    task.metadata["asset_policy"]["allow_procedural_fallback"] = True
    task.metadata["asset_policy"]["require_official_asset"] = False
    task.metadata["asset_policy"]["diagnostic_variant"] = True

    run_dir = out_dir / task.id / f"seed_{chunk_start_seed:03d}_{chunk_start_seed + episodes - 1:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    policy_config = {
        "policy_id": "object_validity_audit",
        "type": "object_validity_audit",
        "policy_type": "object_validity_audit",
        "policy_config_dict": {
            "audit_steps": audit_steps,
            "table_z": table_z,
            "clear_trace_on_reset": False,
        },
        "skill_hints": [],
    }

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=episodes,
        max_steps=audit_steps,
        trace_dir=trace_dir,
    )

    records = _load_trace(trace_path)
    reports = [
        _record_to_report(task.id, chunk_start_seed + r.get("episode", 0), r, table_z=table_z)
        for r in records
        if r.get("audit")
    ]

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")
    for report in reports:
        (run_dir / f"object_validity_step_{report.step}_seed_{report.seed:03d}.json").write_text(
            report.model_dump_json(indent=2)
        )

    asset_info = (result.metadata or {}).get("asset_info", {})
    benchmark_validity = (result.metadata or {}).get("benchmark_validity", {})

    return {
        "task_id": task.id,
        "task_path": task_path,
        "seed": chunk_start_seed,
        "episodes": episodes,
        "status": result.status,
        "audit_records": len(reports),
        "object_validity": [r.model_dump() for r in reports],
        "asset_info": asset_info,
        "benchmark_validity": benchmark_validity,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r)

    summary: dict[str, Any] = {}
    for task_id, task_rows in by_task.items():
        valid_reports: list[ObjectValidityReport] = []
        for r in task_rows:
            for rep in r.get("object_validity", []):
                valid_reports.append(ObjectValidityReport(**rep))
        valid_count = sum(1 for r in valid_reports if r.valid)
        total = len(valid_reports)
        error_counts: dict[str, int] = {}
        for r in valid_reports:
            for e in r.validity_errors:
                error_counts[e] = error_counts.get(e, 0) + 1
        summary[task_id] = {
            "valid_rate": valid_count / total if total else None,
            "valid_count": valid_count,
            "total_reports": total,
            "error_distribution": error_counts,
            "object_z_range": [
                min((r.object_root_pos[2] for r in valid_reports), default=None),
                max((r.object_root_pos[2] for r in valid_reports), default=None),
            ],
            "bbox_valid_rate": sum(1 for r in valid_reports if "invalid_bbox" not in r.validity_errors) / total if total else None,
            "rigid_body_enabled_rate": sum(1 for r in valid_reports if r.rigid_body_enabled) / total if total else None,
            "collision_enabled_rate": sum(1 for r in valid_reports if r.collision_enabled) / total if total else None,
            "object_index_consistency_rate": sum(1 for r in valid_reports if r.object_index_consistent) / total if total else None,
        }
    return summary


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    flat: list[dict[str, Any]] = []
    for r in rows:
        for rep in r.get("object_validity", []):
            flat.append({
                "task_id": r["task_id"],
                "seed": r["seed"],
                "status": r["status"],
                **rep,
            })
    if not flat:
        return
    keys = list(flat[0].keys())
    with path.open("w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for row in flat:
            f.write(",".join(str(row.get(k, "")) for k in keys) + "\n")


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_seeds(args.seeds)
    cleanup = args.cleanup and not args.no_cleanup
    episodes_per_run = getattr(args, "episodes_per_run", 1)
    if episodes_per_run < 1:
        episodes_per_run = 1

    rows: list[dict[str, Any]] = []
    for task_path in args.tasks:
        with open(task_path, "r", encoding="utf-8") as f:
            task_yaml = f.read()
        if episodes_per_run == 1:
            for seed in seeds:
                print(f"\n=== {task_path} seed {seed} ===", file=sys.stderr)
                try:
                    row = _run_audit(
                        task_path,
                        task_yaml,
                        seed,
                        args.audit_steps,
                        args.table_z,
                        out_dir,
                        cleanup=cleanup,
                    )
                except Exception as exc:
                    row = {
                        "task_id": Path(task_path).stem,
                        "task_path": task_path,
                        "seed": seed,
                        "status": f"error: {exc}",
                        "audit_records": 0,
                        "object_validity": [],
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))
        else:
            for i in range(0, len(seeds), episodes_per_run):
                chunk = seeds[i : i + episodes_per_run]
                chunk_start = chunk[0]
                chunk_end = chunk[-1]
                print(
                    f"\n=== {task_path} seeds {chunk_start}:{chunk_end} ({len(chunk)} episodes) ===",
                    file=sys.stderr,
                )
                try:
                    row = _run_audit_batch(
                        task_path,
                        task_yaml,
                        chunk_start,
                        len(chunk),
                        args.audit_steps,
                        args.table_z,
                        out_dir,
                        cleanup=cleanup,
                    )
                except Exception as exc:
                    row = {
                        "task_id": Path(task_path).stem,
                        "task_path": task_path,
                        "seed": chunk_start,
                        "episodes": len(chunk),
                        "status": f"error: {exc}",
                        "audit_records": 0,
                        "object_validity": [],
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows)
    summary["tasks"] = [Path(t).stem for t in args.tasks]
    summary["seeds"] = seeds
    summary["episodes_per_run"] = episodes_per_run
    summary["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    csv_path = out_dir / "per_step_validity.csv"
    json_path = out_dir / "aggregate_summary.json"
    _write_csv(rows, csv_path)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== aggregate summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
