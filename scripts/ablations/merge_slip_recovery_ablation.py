#!/usr/bin/env python3
"""Merge per-GPU slip-aware recovery ablation outputs into a single aggregate.

The parallel ablation launches one runner per GPU, each covering a subset of
conditions.  This script reads their per_run_results.csv files and their
aggregate_summary.json files and writes merged versions to the parent directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


def _load_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def merge(parent_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    gpu_dirs = sorted(d for d in parent_dir.iterdir() if d.is_dir() and d.name.startswith("gpu"))
    if not gpu_dirs:
        raise FileNotFoundError(f"No gpu* subdirectories found under {parent_dir}")

    all_rows: list[dict[str, str]] = []
    summaries: list[dict[str, Any]] = []
    target_yaws: list[float] = []
    conditions: list[str] = []
    seeds: list[int] = []
    task: str | None = None
    base_policy: str | None = None

    for gpu_dir in gpu_dirs:
        rows = _load_csv(gpu_dir / "per_run_results.csv")
        summary = _load_json(gpu_dir / "aggregate_summary.json")
        if summary is None:
            raise ValueError(f"Missing aggregate_summary.json in {gpu_dir}")
        all_rows.extend(rows)
        summaries.append(summary)
        if summary.get("target_yaws"):
            target_yaws = summary["target_yaws"]
        if summary.get("conditions"):
            conditions.extend(summary["conditions"])
        if summary.get("seeds"):
            seeds = summary["seeds"]
        if task is None and summary.get("task"):
            task = summary["task"]
        if base_policy is None and summary.get("base_policy"):
            base_policy = summary["base_policy"]

    merged_summary: dict[str, Any] = {
        "per_condition_target": {},
        "target_yaws": target_yaws,
        "seeds": seeds,
        "conditions": sorted(set(conditions)),
        "task": task,
        "base_policy": base_policy,
        "merged_from": [str(d) for d in gpu_dirs],
    }
    for summary in summaries:
        merged_summary["per_condition_target"].update(summary.get("per_condition_target", {}))

    return all_rows, merged_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge per-GPU slip recovery ablation outputs")
    parser.add_argument("parent_dir", type=Path, help="Directory containing gpu* subdirectories")
    args = parser.parse_args()

    rows, summary = merge(args.parent_dir)

    csv_path = args.parent_dir / "per_run_results.csv"
    json_path = args.parent_dir / "aggregate_summary.json"

    if rows:
        keys = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Merged CSV: {csv_path} ({len(rows)} rows)")

    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"Merged JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
