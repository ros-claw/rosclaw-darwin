#!/usr/bin/env python3
"""ContactSignal reliability audit across multiple phases and task sources.

v1.10 Sprint 2 extends ContactSignal coverage beyond CONTACT_VERIFY to
GRASP / LIFT / ALIGN / HOLD / RECOVERY.  This script computes per-phase
coverage, state distribution, legacy-proxy agreement, and missing-signal
rates from existing traces or from fresh Arena runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

# Allow direct execution without editable install.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rosclaw_darwin.adapters.arena import ArenaAdapter  # noqa: E402
from rosclaw_darwin.evaluation.contact_signal import ContactSignalProvider  # noqa: E402
from rosclaw_darwin.tdl.loader import TaskLoader  # noqa: E402

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_OUT_DIR = Path("data_v20/diagnostics/contact_signal_reliability_audit")

# Phases that v1.10 requires ContactSignal to cover.
REQUIRED_PHASES = {"GRASP", "LIFT", "ALIGN", "HOLD", "RECOVERY", "CONTACT_VERIFY"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ContactSignal reliability audit")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--seeds", type=str, default="0,1,24")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--from-traces", type=Path, help="Directory containing seed_*/trace.jsonl files to audit")
    parser.add_argument("--run-arena", action="store_true", help="Run fresh Arena evaluations")
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
    killed = 0
    for cid in container_ids:
        kill_result = subprocess.run(
            ["docker", "kill", cid], capture_output=True, text=True, check=False
        )
        if kill_result.returncode == 0:
            killed += 1
    return killed


def _parse_seed_range(text: str) -> list[int]:
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    seeds: list[int] = []
    for p in parts:
        if ":" in p:
            start, end = p.split(":", 1)
            seeds.extend(range(int(start), int(end) + 1))
        else:
            seeds.append(int(p))
    return sorted(set(seeds))


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


def _find_trace_dirs(root: Path) -> list[Path]:
    """Find directories containing trace.jsonl under root."""
    return sorted([p.parent for p in root.rglob("trace.jsonl")])


def _extract_seed_from_dir(trace_dir: Path) -> int | None:
    """Infer seed from directory name like seed000, seed_000, or seed-000."""
    name = trace_dir.name
    for prefix in ("seed_", "seed-", "seed"):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix):])
            except ValueError:
                pass
    return None


def _normalize_phase(raw_phase: str) -> str | None:
    """Map policy-specific phase names to v1.10 required phases."""
    phase = str(raw_phase or "UNKNOWN").upper()
    if phase == "LIFT_VERIFY":
        return "LIFT"
    if "RECOVER" in phase:
        return "RECOVERY"
    if phase in REQUIRED_PHASES:
        return phase
    return None


def _audit_trace(trace: list[dict[str, Any]], provider: ContactSignalProvider) -> dict[str, Any]:
    """Compute per-phase contact-signal statistics for a single trace."""
    provider.reset()

    phase_steps: dict[str, int] = defaultdict(int)
    phase_with_signal: dict[str, int] = defaultdict(int)
    phase_state_counts: dict[str, Counter] = defaultdict(Counter)
    phase_proxy_agreements: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    phase_disagreements: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for frame in trace:
        phase = _normalize_phase(frame.get("phase"))
        if phase is None:
            continue

        # Prefer pre-computed contact_state in the trace; otherwise recompute.
        trace_state = frame.get("contact_state")
        trace_confidence = frame.get("contact_confidence")
        trace_reason = frame.get("contact_reason")
        trace_proxy = frame.get("contact_proxy") or "unknown"

        if trace_state is None:
            signal = provider.compute_from_kinematics(frame)
            state = signal.contact_state
            confidence = signal.contact_confidence
            reason = signal.reason
        else:
            state = trace_state
            confidence = trace_confidence if trace_confidence is not None else 0.0
            reason = trace_reason

        phase_steps[phase] += 1
        phase_state_counts[phase][state] += 1

        if state != "unknown":
            phase_with_signal[phase] += 1

        # Compare with legacy contact_proxy only in CONTACT_VERIFY, where the
        # legacy proxy is known to be meaningful.
        if phase == "CONTACT_VERIFY" and trace_proxy != "unknown" and state != "unknown":
            agreed, total = phase_proxy_agreements[phase]
            total += 1
            if trace_proxy == state:
                agreed += 1
            elif len(phase_disagreements[phase]) < 3:
                phase_disagreements[phase].append(
                    {
                        "step": frame.get("step"),
                        "proxy": trace_proxy,
                        "state": state,
                        "confidence": confidence,
                        "reason": reason,
                    }
                )
            phase_proxy_agreements[phase] = (agreed, total)

    phase_metrics: dict[str, dict[str, Any]] = {}
    for phase in REQUIRED_PHASES:
        steps = phase_steps.get(phase, 0)
        with_signal = phase_with_signal.get(phase, 0)
        agreed, compared = phase_proxy_agreements.get(phase, (0, 0))
        metrics = {
            "steps": steps,
            "coverage_rate": round(with_signal / steps, 4) if steps else 0.0,
            "missing_signal_rate": round(
                phase_state_counts[phase].get("unknown", 0) / steps, 4
            )
            if steps
            else 0.0,
            "state_distribution": dict(phase_state_counts[phase]),
            "legacy_proxy_compared": compared,
            "legacy_proxy_agreed": agreed,
            "legacy_proxy_agreement_rate": round(agreed / compared, 4) if compared else 0.0,
            "disagreement_examples": phase_disagreements.get(phase, []),
        }
        phase_metrics[phase] = metrics

    return {
        "phase_metrics": phase_metrics,
        "total_frames_audited": sum(phase_steps.values()),
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
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )

    trace = _load_trace(trace_path)
    provider = ContactSignalProvider()
    audit = _audit_trace(trace, provider)

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    metrics = result.metrics or {}
    return {
        "seed": seed,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "env_progress_mean": metrics.get("progress_mean"),
        **audit,
    }


def _audit_existing_traces(trace_root: Path) -> list[dict[str, Any]]:
    trace_dirs = _find_trace_dirs(trace_root)
    rows: list[dict[str, Any]] = []
    for trace_dir in trace_dirs:
        seed = _extract_seed_from_dir(trace_dir)
        trace = _load_trace(trace_dir / "trace.jsonl")
        provider = ContactSignalProvider()
        audit = _audit_trace(trace, provider)
        rows.append(
            {
                "seed": seed,
                "source_dir": str(trace_dir),
                "status": "from_trace",
                **audit,
            }
        )
    return rows


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


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-phase metrics across all audited seeds."""
    aggregate_phase: dict[str, dict[str, Any]] = {}
    for phase in REQUIRED_PHASES:
        total_steps = sum(r["phase_metrics"][phase]["steps"] for r in rows if "phase_metrics" in r)
        total_with_signal = sum(
            r["phase_metrics"][phase]["steps"] - r["phase_metrics"][phase]["state_distribution"].get("unknown", 0)
            for r in rows
            if "phase_metrics" in r
        )
        total_unknown = sum(
            r["phase_metrics"][phase]["state_distribution"].get("unknown", 0)
            for r in rows
            if "phase_metrics" in r
        )
        total_compared = sum(
            r["phase_metrics"][phase]["legacy_proxy_compared"] for r in rows if "phase_metrics" in r
        )
        total_agreed = sum(
            r["phase_metrics"][phase]["legacy_proxy_agreed"] for r in rows if "phase_metrics" in r
        )

        state_counter: Counter = Counter()
        for r in rows:
            if "phase_metrics" not in r:
                continue
            for state, count in r["phase_metrics"][phase]["state_distribution"].items():
                state_counter[state] += count

        aggregate_phase[phase] = {
            "total_steps": total_steps,
            "coverage_rate": round(total_with_signal / total_steps, 4) if total_steps else 0.0,
            "missing_signal_rate": round(total_unknown / total_steps, 4) if total_steps else 0.0,
            "state_distribution": dict(state_counter),
            "legacy_proxy_compared": total_compared,
            "legacy_proxy_agreement_rate": round(total_agreed / total_compared, 4)
            if total_compared
            else 0.0,
        }

    return {
        "num_seeds": len(rows),
        "phases": aggregate_phase,
        "overall_coverage_rate": round(
            sum(
                aggregate_phase[p]["total_steps"] - aggregate_phase[p]["state_distribution"].get("unknown", 0)
                for p in REQUIRED_PHASES
            )
            / sum(aggregate_phase[p]["total_steps"] for p in REQUIRED_PHASES),
            4,
        )
        if any(aggregate_phase[p]["total_steps"] for p in REQUIRED_PHASES)
        else 0.0,
    }


def main() -> int:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cleanup = args.cleanup and not args.no_cleanup

    rows: list[dict[str, Any]] = []
    source = "from_traces"

    if args.from_traces:
        trace_root: Path = args.from_traces.resolve()
        if not trace_root.exists():
            print(f"Trace root not found: {trace_root}", file=sys.stderr)
            return 1
        rows = _audit_existing_traces(trace_root)
        source = f"from_traces:{trace_root}"
    elif args.run_arena:
        with open(args.policy, "r", encoding="utf-8") as f:
            policy_config = yaml.safe_load(f) or {}
        policy_config.setdefault("policy_id", Path(args.policy).stem)
        policy_config["policy_source"] = args.policy
        policy_config.setdefault("policy_config_dict", {})
        policy_config["policy_config_dict"]["enable_contact_signal"] = True

        seeds = _parse_seed_range(args.seeds)
        for seed in seeds:
            print(f"\n=== seed {seed} ===", file=sys.stderr)
            try:
                row = _run_seed(args.task, policy_config, seed, out_dir, cleanup=cleanup)
            except Exception as exc:
                row = {
                    "seed": seed,
                    "status": f"error: {exc}",
                    "total_frames_audited": 0,
                }
            rows.append(row)
            print(json.dumps(row, indent=2, default=str))
        source = f"run_arena:{args.policy}:{args.seeds}"
    else:
        print("Either --from-traces or --run-arena must be specified", file=sys.stderr)
        return 1

    aggregate = _aggregate(rows)
    summary = {
        "task": args.task,
        "policy": args.policy,
        "source": source,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **aggregate,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
