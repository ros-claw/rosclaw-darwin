#!/usr/bin/env python3
"""Validate the kinematic slip monitor on v1.7 large-yaw traces.

Loads the traces produced by the large-yaw matrix
(``data_v17/diagnostics/large_yaw_slip``), labels each trace as success/failure
from ``per_run_results.csv``, runs ``SlipMonitor``, and reports detection
statistics: recall on failures, false-positive rate on successes, and median
early-detection step count.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.slip_monitor import SlipMonitor, SlipMonitorConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate slip monitor on large-yaw goal_pose traces"
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=Path("data_v17/diagnostics/large_yaw_slip"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data_v18/diagnostics/slip_monitor_validation"),
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Slip event score threshold (default: from SlipMonitorConfig)",
    )
    return parser.parse_args()


def _load_trace(trace_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not trace_path.exists():
        return records
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_labels(trace_dir: Path) -> dict[tuple[int, float], dict[str, Any]]:
    """Return {(seed, rounded_yaw): row} from per_run_results.csv."""
    labels: dict[tuple[int, float], dict[str, Any]] = {}
    csv_path = trace_dir / "per_run_results.csv"
    if not csv_path.exists():
        return labels
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                seed = int(row["seed"])
                yaw = round(float(row["target_yaw"]), 4)
            except (KeyError, ValueError):
                continue
            labels[(seed, yaw)] = row
    return labels


def _find_trace_files(trace_dir: Path) -> list[Path]:
    """Find trace.jsonl files under yaw_*/seed_*/ directories."""
    files: list[Path] = []
    for yaw_dir in sorted(trace_dir.glob("yaw_*")):
        if not yaw_dir.is_dir():
            continue
        for seed_dir in sorted(yaw_dir.glob("seed_*")):
            if not seed_dir.is_dir():
                continue
            # Prefer the top-level copied trace.
            trace_path = seed_dir / "trace.jsonl"
            if not trace_path.exists():
                trace_path = seed_dir / "traces" / "episode_trace.jsonl"
            if trace_path.exists():
                files.append(trace_path)
    return files


def _parse_yaw_from_dir(yaw_dir: Path) -> float:
    """Parse target yaw from directory name like 'yaw_1.5708'."""
    try:
        return float(yaw_dir.name.replace("yaw_", ""))
    except ValueError:
        return 0.0


def _parse_seed_from_dir(seed_dir: Path) -> int:
    try:
        return int(seed_dir.name.replace("seed_", ""))
    except ValueError:
        return -1


def _run_validation(
    trace_dir: Path,
    out_dir: Path,
    score_threshold: float | None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = _load_labels(trace_dir)
    trace_files = _find_trace_files(trace_dir)

    monitor = SlipMonitor(SlipMonitorConfig())

    per_trace_rows: list[dict[str, Any]] = []
    by_yaw: dict[float, dict[str, Any]] = {}

    for trace_path in trace_files:
        seed = _parse_seed_from_dir(trace_path.parent)
        yaw = round(_parse_yaw_from_dir(trace_path.parent.parent), 4)
        label_row = labels.get((seed, yaw), {})
        category = label_row.get("category", "unknown")
        orientation_achieved = label_row.get("orientation_achieved", "").lower() == "true"
        failed = not orientation_achieved

        trace = _load_trace(trace_path)
        if not trace:
            continue

        events = monitor.detect_events(trace, threshold=score_threshold)
        signals = monitor.process_trace(trace)
        max_score = max((s.slip_score for s in signals), default=0.0)
        first_event = events[0] if events else None
        final_step = trace[-1].get("step", len(trace) - 1)

        row = {
            "trace_path": str(trace_path.relative_to(trace_dir)),
            "seed": seed,
            "target_yaw": yaw,
            "category": category,
            "failed": failed,
            "num_events": len(events),
            "first_event_step": first_event["start_step"] if first_event else None,
            "first_event_phase": first_event["first_phase"] if first_event else None,
            "first_event_dominant_type": first_event["dominant_type"] if first_event else None,
            "max_score": max_score,
            "final_step": final_step,
        }
        if first_event is not None and final_step is not None:
            row["early_detection_steps"] = final_step - first_event["start_step"]
        else:
            row["early_detection_steps"] = None
        per_trace_rows.append(row)

        by_yaw.setdefault(
            yaw,
            {
                "total": 0,
                "failed": 0,
                "success": 0,
                "detected_failures": 0,
                "undetected_failures": 0,
                "false_positives": 0,
                "true_negatives": 0,
                "early_detection_steps": [],
                "category_counts": {},
            },
        )
        agg = by_yaw[yaw]
        agg["total"] += 1
        agg["category_counts"][category] = agg["category_counts"].get(category, 0) + 1
        if failed:
            agg["failed"] += 1
            if first_event is not None:
                agg["detected_failures"] += 1
                if row["early_detection_steps"] is not None:
                    agg["early_detection_steps"].append(row["early_detection_steps"])
            else:
                agg["undetected_failures"] += 1
        else:
            agg["success"] += 1
            if first_event is not None:
                agg["false_positives"] += 1
            else:
                agg["true_negatives"] += 1

    # Summarize by yaw and overall.
    def _summarize(agg: dict[str, Any]) -> dict[str, Any]:
        failed = agg["failed"]
        success = agg["success"]
        detected = agg["detected_failures"]
        fp = agg["false_positives"]
        early = agg["early_detection_steps"]
        return {
            "total": agg["total"],
            "failed": failed,
            "success": success,
            "recall_on_failures": detected / failed if failed else None,
            "precision_on_detections": detected / (detected + fp) if (detected + fp) else None,
            "false_positive_rate_on_success": fp / success if success else None,
            "median_early_detection_steps": sorted(early)[len(early) // 2] if early else None,
            "mean_early_detection_steps": sum(early) / len(early) if early else None,
            "category_counts": dict(agg["category_counts"]),
        }

    overall_agg = {
        "total": sum(a["total"] for a in by_yaw.values()),
        "failed": sum(a["failed"] for a in by_yaw.values()),
        "success": sum(a["success"] for a in by_yaw.values()),
        "detected_failures": sum(a["detected_failures"] for a in by_yaw.values()),
        "undetected_failures": sum(a["undetected_failures"] for a in by_yaw.values()),
        "false_positives": sum(a["false_positives"] for a in by_yaw.values()),
        "true_negatives": sum(a["true_negatives"] for a in by_yaw.values()),
        "early_detection_steps": [
            s
            for a in by_yaw.values()
            for s in a["early_detection_steps"]
        ],
        "category_counts": {},
    }

    summary: dict[str, Any] = {
        "by_yaw": {str(yaw): _summarize(agg) for yaw, agg in by_yaw.items()},
        "overall": _summarize(overall_agg),
        "score_threshold": score_threshold,
        "trace_dir": str(trace_dir),
        "num_traces": len(trace_files),
    }

    # Write outputs.
    csv_path = out_dir / "per_trace_results.csv"
    json_path = out_dir / "aggregate_summary.json"
    if per_trace_rows:
        keys = list(per_trace_rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(per_trace_rows)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary


def main() -> None:
    args = parse_args()
    summary = _run_validation(args.trace_dir, args.out_dir, args.score_threshold)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
