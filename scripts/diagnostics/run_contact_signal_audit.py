#!/usr/bin/env python3
"""ContactSignal audit: run seeds with contact-signal enabled and compare with legacy proxy.

This Sprint 2 diagnostic verifies that the new ContactSignalProvider produces
contact_state values that are consistent with the legacy heuristic_policy
_contact_proxy classification, while also exposing the richer ContactSignal
fields (confidence, source, force estimates).
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

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_OUT_DIR = Path("data_v19/diagnostics/contact_signal_audit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ContactSignal audit")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--seeds", type=str, default="0,24,58,78,86,96")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    return parser.parse_args()


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


def _parse_seed_range(text: str) -> list[int]:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    seeds: list[int] = []
    for p in parts:
        if ":" in p:
            start, end = p.split(":", 1)
            seeds.extend(range(int(start), int(end) + 1))
        else:
            seeds.append(int(p))
    return seeds


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


def _compare_states(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare legacy contact_proxy with new contact_state.

    The legacy ``contact_proxy`` field is only populated during the
    ``CONTACT_VERIFY`` phase, and it reports ``unknown`` on the first
    verification step while the diagnosis state is still initializing.
    Comparison is therefore restricted to ``CONTACT_VERIFY`` steps where
    the legacy proxy has produced a real classification.
    """
    total = 0
    agreed = 0
    state_counts: dict[str, int] = {}
    proxy_counts: dict[str, int] = {}
    disagreement_examples: list[dict[str, Any]] = []
    for r in records:
        phase = r.get("phase", "")
        proxy = r.get("contact_proxy") or "unknown"
        state = r.get("contact_state") or "unknown"
        # Legacy proxy is only meaningful in CONTACT_VERIFY.
        if phase != "CONTACT_VERIFY":
            continue
        # Skip steps where the legacy proxy has not yet classified.  This
        # avoids penalizing ContactSignal for being one step more responsive
        # than the legacy heuristic.
        if proxy == "unknown":
            continue
        proxy_counts[proxy] = proxy_counts.get(proxy, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1
        total += 1
        # Treat None/missing as unknown for agreement.
        if proxy == state:
            agreed += 1
        elif len(disagreement_examples) < 5:
            disagreement_examples.append(
                {
                    "step": r.get("step"),
                    "phase": phase,
                    "proxy": proxy,
                    "state": state,
                    "confidence": r.get("contact_confidence"),
                }
            )
    return {
        "compared_steps": total,
        "agreed_steps": agreed,
        "agreement_rate": agreed / total if total else 0.0,
        "state_distribution": state_counts,
        "proxy_distribution": proxy_counts,
        "disagreement_examples": disagreement_examples,
    }


def _run_seed(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed{seed:03d}"
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
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )

    trace = _load_trace(trace_path)
    comparison = _compare_states(trace)

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    metrics = result.metrics or {}
    return {
        "seed": seed,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "env_progress_mean": metrics.get("progress_mean"),
        **comparison,
    }


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


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cleanup = args.cleanup and not args.no_cleanup

    with open(args.policy, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(args.policy).stem)
    policy_config["policy_source"] = args.policy
    policy_config.setdefault("policy_config_dict", {})
    policy_config["policy_config_dict"]["enable_contact_signal"] = True

    seeds = _parse_seed_range(args.seeds)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        print(f"\n=== seed {seed} ===", file=sys.stderr)
        try:
            row = _run_seed(args.task, policy_config, seed, out_dir, cleanup=cleanup)
        except Exception as exc:
            row = {
                "seed": seed,
                "status": f"error: {exc}",
                "compared_steps": 0,
                "agreement_rate": 0.0,
            }
        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

    valid = [r for r in rows if not str(r.get("status", "")).startswith("error")]
    successes = [r for r in valid if r.get("env_success_rate") == 1.0]
    comparable = [r for r in valid if r.get("compared_steps", 0) > 0]
    agreement_rates = [
        r.get("agreement_rate") for r in comparable if r.get("agreement_rate") is not None
    ]
    summary = {
        "task": args.task,
        "policy": args.policy,
        "seeds": args.seeds,
        "num_seeds": len(seeds),
        "valid_runs": len(valid),
        "success_runs": len(successes),
        "success_rate": len(successes) / len(valid) if valid else 0.0,
        "comparable_runs": len(comparable),
        "mean_agreement_rate": sum(agreement_rates) / len(agreement_rates) if agreement_rates else 0.0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    csv_path = out_dir / "per_seed_results.csv"
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
