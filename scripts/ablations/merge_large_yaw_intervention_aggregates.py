#!/usr/bin/env python3
"""Merge a supplementary large-yaw intervention aggregate into the main one.

Usage example after running the table_push_align-only ablation:

    python scripts/ablations/merge_large_yaw_intervention_aggregates.py \
        --source data_v17/ablations/large_yaw_intervention_table_push_align/aggregate_summary.json \
        --target data_v17/ablations/large_yaw_intervention/aggregate_summary.json \
        --out-dir data_v17/ablations/large_yaw_intervention
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge large-yaw intervention aggregates")
    parser.add_argument("--source", required=True, help="Source aggregate JSON with new conditions")
    parser.add_argument("--target", required=True, help="Target aggregate JSON to merge into")
    parser.add_argument("--out-dir", type=Path, help="Directory to write merged files")
    return parser.parse_args()


def _load(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    args = parse_args()
    source = _load(args.source)
    target = _load(args.target)

    merged = dict(target)
    merged.setdefault("per_condition_target", {}).update(source.get("per_condition_target", {}))

    # Merge conditions and target yaws uniquely while preserving order.
    for key in ("conditions", "target_yaws"):
        seen: set[Any] = set()
        combined: list[Any] = []
        for value in list(target.get(key, [])) + list(source.get(key, [])):
            if value not in seen:
                seen.add(value)
                combined.append(value)
        merged[key] = combined

    # Seeds should be the same; take the union to be safe.
    if "seeds" in source and "seeds" in target:
        merged["seeds"] = sorted(set(target["seeds"]) | set(source["seeds"]))

    out_dir = args.out_dir or Path(args.target).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "aggregate_summary.json"

    # Back up the original target before overwriting.
    backup_path = out_dir / "aggregate_summary.pre_merge.json"
    shutil.copy(args.target, backup_path)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, default=str)

    print(f"Merged aggregate written to {out_path}")
    print(f"Backup of original target at {backup_path}")
    print(f"Conditions: {merged.get('conditions')}")


if __name__ == "__main__":
    main()
