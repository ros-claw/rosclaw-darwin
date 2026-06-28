#!/usr/bin/env python3
"""Diagnose approach-collision dominated failures from paired evaluation data.

This is an independent FailureToHint v3.4 diagnosis route.  It reads the paired
evaluation summary and per-seed failure-signature artifacts, identifies seeds
whose dominant failure class is ``approach_collision``, and produces a JSON
manifest plus a markdown report.  The route is intentionally diagnosis-only:
there is no paired evidence that the current policy can recover these cases,
so they are kept out of the grip-quality micro-recovery evidence pool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose approach-collision failures from paired evaluation"
    )
    parser.add_argument(
        "--paired-summary",
        default="data_v20/paired/official_seed24_micro_recovery_0_199/paired_summary.json",
        help="Path to paired evaluation summary JSON",
    )
    parser.add_argument(
        "--out-dir",
        default="data_v20/diagnostics/approach_collision_diagnosis",
        help="Directory for the JSON manifest",
    )
    parser.add_argument(
        "--report",
        default="reports/APPROACH_COLLISION_DIAGNOSIS_REPORT.md",
        help="Path to the markdown report to generate",
    )
    return parser.parse_args()


def _load_failure_signature(artifact_dir: str) -> dict[str, Any]:
    path = Path(artifact_dir) / "failure_signature.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_approach_collision_seeds(
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return structured statistics about approach-collision dominated seeds."""
    baseline_only: list[int] = []
    candidate_only: list[int] = []
    both: list[int] = []
    neither_but_pair_failed: list[int] = []

    for outcome in outcomes:
        seed = outcome["seed"]
        baseline_fc = outcome.get("baseline_failure_type") or "unknown"
        candidate_fc = outcome.get("candidate_failure_type") or "unknown"
        baseline_is_ac = baseline_fc == "approach_collision"
        candidate_is_ac = candidate_fc == "approach_collision"

        if baseline_is_ac and candidate_is_ac:
            both.append(seed)
        elif baseline_is_ac:
            baseline_only.append(seed)
        elif candidate_is_ac:
            candidate_only.append(seed)
        elif outcome.get("delta_class") in {"unchanged_failure", "newly_failed"}:
            neither_but_pair_failed.append(seed)

    all_ac_seeds = sorted(set(baseline_only) | set(candidate_only) | set(both))

    return {
        "approach_collision_seeds": all_ac_seeds,
        "baseline_only": sorted(baseline_only),
        "candidate_only": sorted(candidate_only),
        "both": sorted(both),
        "other_failed_seeds": sorted(neither_but_pair_failed),
        "count": len(all_ac_seeds),
    }


def _enrich_with_failure_signatures(
    outcomes: list[dict[str, Any]], ac_seeds: list[int]
) -> list[dict[str, Any]]:
    """Attach per-seed failure-signature metadata for approach-collision seeds."""
    seed_set = set(ac_seeds)
    enriched: list[dict[str, Any]] = []
    for outcome in outcomes:
        if outcome["seed"] not in seed_set:
            continue
        row: dict[str, Any] = {
            "seed": outcome["seed"],
            "delta_class": outcome.get("delta_class"),
            "baseline_failure_type": outcome.get("baseline_failure_type"),
            "candidate_failure_type": outcome.get("candidate_failure_type"),
        }
        baseline_sig = _load_failure_signature(outcome.get("baseline_artifact_dir", ""))
        candidate_sig = _load_failure_signature(outcome.get("candidate_artifact_dir", ""))
        row["baseline_signature"] = {
            "failure_class": baseline_sig.get("failure_class"),
            "anomaly_tags": baseline_sig.get("anomaly_tags", []),
        }
        row["candidate_signature"] = {
            "failure_class": candidate_sig.get("failure_class"),
            "anomaly_tags": candidate_sig.get("anomaly_tags", []),
        }
        enriched.append(row)
    return enriched


def _write_markdown_report(
    report_path: Path,
    summary: dict[str, Any],
    ac_stats: dict[str, Any],
    enriched: list[dict[str, Any]],
) -> None:
    lines: list[str] = [
        "# Approach-Collision Failure Diagnosis Report",
        "",
        "**Date:** 2026-06-26  ",
        "**Route:** `approach_collision_diagnosis` (FailureToHint v3.4)",
        "**Status:** `diagnosis_only` / `experimental_only`",
        "",
        "---",
        "",
        "## Goal",
        "",
        "Separate approach-collision failures from the seed-24 grip-quality",
        "micro-recovery evidence pool.  Approach collisions are a distinct",
        "failure boundary (workspace / placement geometry) and must not be",
        "counted as grip-quality micro-recovery candidates.",
        "",
        "## Method",
        "",
        "Read the paired-evaluation summary and per-seed",
        "`failure_signature.json` artifacts.  A seed is classified as",
        "approach-collision dominated if either the baseline or the candidate",
        "failure class is `approach_collision`.",
        "",
        "## Source evidence",
        "",
        f"- Paired summary: `{summary.get('task_id')}`",
        f"- Seeds covered: `{summary.get('seed_range')}`",
        f"- Total pairs: {summary.get('total_pairs')}",
        f"- Valid pairs: {summary.get('valid_pairs')}",
        "",
        "## Results",
        "",
        f"- **Approach-collision dominated seeds:** {ac_stats['count']}",
        f"- **Both sides:** {len(ac_stats['both'])} — {ac_stats['both']}",
        f"- **Baseline only:** {len(ac_stats['baseline_only'])} — {ac_stats['baseline_only']}",
        f"- **Candidate only:** {len(ac_stats['candidate_only'])} — {ac_stats['candidate_only']}",
        "",
        "## Seed detail",
        "",
        "| Seed | Delta class | Baseline failure | Candidate failure |",
        "|---|---|---|---|",
    ]
    for row in enriched:
        lines.append(
            f"| {row['seed']} | {row['delta_class']} | "
            f"{row['baseline_failure_type']} | {row['candidate_failure_type']} |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        "Approach-collision dominated seeds are concentrated in the official",
        "dex_cube benchmark when initial placement geometry causes the gripper",
        "to collide with the cube or surrounding workspace during the",
        "approach phase.  These failures are independent of the grip-quality",
        "micro-recovery axis and should be tracked by their own diagnosis route.",
        "",
        "## FailureToHint v3.4 route",
        "",
        "The `approach_collision_diagnosis` rule declares:",
        "",
        "- `route_selection`: `diagnosis_only`",
        "- `claim_level`: `diagnosis_only`",
        "- `promotion_status`: `experimental`",
        "- No `evidence_gate`: promotion is blocked until dedicated paired",
        "  evidence for an approach-collision recovery candidate is available.",
        "",
        "## Next steps",
        "",
        "1. Keep approach-collision seeds out of the seed-24 micro-recovery",
        "   promotion evidence.",
        "2. If a future approach planner / reachability intervention is",
        "   developed, evaluate it with its own paired no-regression sweep",
        "   on these seeds.",
        "3. Only promote to `candidate_recovery` when a dedicated gate",
        "  (e.g. `paired_no_regression` on approach-collision seeds) is met.",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()

    summary_path = Path(args.paired_summary)
    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    summary = summary_data.get("summary", summary_data)
    outcomes = summary_data.get("outcomes", [])

    ac_stats = _collect_approach_collision_seeds(outcomes)
    enriched = _enrich_with_failure_signatures(outcomes, ac_stats["approach_collision_seeds"])

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "summary_source": str(summary_path.resolve()),
        "task_id": summary.get("task_id"),
        "seed_range": summary.get("seed_range"),
        "total_pairs": summary.get("total_pairs"),
        "valid_pairs": summary.get("valid_pairs"),
        "approach_collision_statistics": ac_stats,
        "approach_collision_seed_details": enriched,
    }
    manifest_path = out_dir / "approach_collision_diagnosis.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")

    report_path = Path(args.report)
    _write_markdown_report(report_path, summary, ac_stats, enriched)
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
