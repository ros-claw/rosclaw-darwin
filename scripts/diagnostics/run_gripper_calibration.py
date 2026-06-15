#!/usr/bin/env python3
"""Run gripper closure calibration (empty or blocked) and report limits.

This script can be invoked directly with --scenario, or via the thin wrappers:
  run_gripper_empty_close_calibration.py
  run_gripper_blocked_close_calibration.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.grasp_metrics import infer_grasp_stability
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose.yaml"
_TRACE_PATH = Path("/tmp/rosclaw_data/traces/episode_trace.jsonl")


def _read_trace() -> list[dict]:
    if not _TRACE_PATH.exists():
        return []
    lines = _TRACE_PATH.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _compute_calibration_metrics(trace: list[dict], scenario: str) -> dict:
    gripper_positions = [s.get("gripper_pos") for s in trace if s.get("gripper_pos") is not None]
    object_positions = [
        (s.get("object_x"), s.get("object_y"), s.get("object_z"))
        for s in trace
        if s.get("object_z") is not None
    ]

    min_gripper = min(gripper_positions) if gripper_positions else None
    final_gripper = gripper_positions[-1] if gripper_positions else None

    object_initial = object_positions[0] if object_positions else None
    object_final = object_positions[-1] if object_positions else None
    object_moved = False
    object_lifted = False
    if object_initial and object_final:
        object_moved = any(
            abs(object_final[i] - object_initial[i]) > 1e-4 for i in range(3)
        )
        object_lifted = (object_final[2] - object_initial[2]) > 0.05

    stability = infer_grasp_stability(trace)

    return {
        "scenario": scenario,
        "steps": len(trace),
        "min_gripper_pos": min_gripper,
        "final_gripper_pos": final_gripper,
        "object_moved": object_moved,
        "object_lifted": object_lifted,
        "object_height_initial": object_initial[2] if object_initial else None,
        "object_height_final": object_final[2] if object_final else None,
        "grasp_stability": {
            k: v for k, v in stability.items() if k not in {"per_episode"}
        },
    }


def run_calibration(
    scenario: str,
    close_commands: list[float],
    close_steps: int,
    task_path: str,
    out_dir: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    task = TaskLoader().load(task_path)
    adapter = ArenaAdapter(task)

    results: list[dict] = []
    for cmd in close_commands:
        # Clear stale trace so each command gets its own file.
        if _TRACE_PATH.exists():
            _TRACE_PATH.unlink()

        policy_config = {
            "policy_type": "gripper_calibration",
            "policy_config_dict": {
                "scenario": scenario,
                "close_command": cmd,
                "close_steps": close_steps,
                "approach_offset_z": 0.12,
                "grasp_offset_z": 0.0,
                "kp": 5.0,
            },
        }

        max_steps = close_steps + (200 if scenario == "blocked_close" else 0)
        result = adapter.run_policy(policy_config, episodes=1, max_steps=max_steps)

        trace = _read_trace()
        metrics = _compute_calibration_metrics(trace, scenario)
        metrics["close_command"] = cmd
        metrics["arena_status"] = result.status
        metrics["arena_metrics"] = result.metrics
        results.append(metrics)

        # Persist trace with command/scenario stamp.
        if trace:
            stamped = out_dir / f"trace_{scenario}_cmd{cmd:.2f}_{int(time.time())}.jsonl"
            shutil.copy(_TRACE_PATH, stamped)

    summary = {
        "scenario": scenario,
        "task": task_path,
        "close_steps": close_steps,
        "commands": close_commands,
        "results": results,
    }
    out_path = out_dir / f"{scenario}_calibration_{int(time.time())}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gripper closure calibration")
    parser.add_argument("--scenario", choices=["empty_close", "blocked_close"], required=True)
    parser.add_argument(
        "--close-command",
        type=float,
        action="append",
        help="Gripper close command magnitude (can be given multiple times).",
    )
    parser.add_argument("--close-steps", type=int, default=100)
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/rosclaw_data/calibrations"))
    args = parser.parse_args(argv[1:] if argv else None)

    commands = args.close_command or [-1.0]
    summary = run_calibration(
        scenario=args.scenario,
        close_commands=commands,
        close_steps=args.close_steps,
        task_path=args.task,
        out_dir=args.out_dir,
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
