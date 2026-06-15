#!/usr/bin/env python3
"""Rotational action calibration for franka_ik relative mode.

Sweeps action[..., 3], action[..., 4], action[..., 5] and records the
resulting end-effector roll/pitch/yaw deltas.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose.yaml"
_TRACE_PATH = Path("/tmp/rosclaw_data/traces/episode_trace.jsonl")

_AXIS_NAMES = {3: "rot_x", 4: "rot_y", 5: "rot_z"}


def _read_trace() -> list[dict]:
    if not _TRACE_PATH.exists():
        return []
    lines = _TRACE_PATH.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _run_trial(adapter, axis, sign, magnitude, steps):
    if _TRACE_PATH.exists():
        _TRACE_PATH.unlink()

    policy_config = {
        "policy_type": "rotational_calibration",
        "policy_config_dict": {
            "calibration_axis": axis,
            "calibration_sign": sign,
            "calibration_magnitude": magnitude,
            "calibration_steps": steps,
        },
    }
    arena_result = adapter.run_policy(policy_config, episodes=1, max_steps=steps)
    trace = _read_trace()
    if len(trace) < 2:
        return {"error": "insufficient trace", "status": arena_result.status}

    initial = trace[0]
    final = trace[-1]
    return {
        "axis_index": axis,
        "axis_name": _AXIS_NAMES[axis],
        "sign": sign,
        "magnitude": magnitude,
        "steps": steps,
        "status": arena_result.status,
        "initial_eef_rpy": {
            "roll": initial.get("eef_roll"),
            "pitch": initial.get("eef_pitch"),
            "yaw": initial.get("eef_yaw"),
        },
        "final_eef_rpy": {
            "roll": final.get("eef_roll"),
            "pitch": final.get("eef_pitch"),
            "yaw": final.get("eef_yaw"),
        },
        "delta_eef_rpy": {
            "roll": final.get("eef_roll") - initial.get("eef_roll"),
            "pitch": final.get("eef_pitch") - initial.get("eef_pitch"),
            "yaw": final.get("eef_yaw") - initial.get("eef_yaw"),
        },
        "delta_pos": {
            "x": final.get("eef_x") - initial.get("eef_x"),
            "y": final.get("eef_y") - initial.get("eef_y"),
            "z": final.get("eef_z") - initial.get("eef_z"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotational action calibration")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--magnitudes", type=float, nargs="+", default=[0.5, 1.0])
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/rosclaw_data/calibrations"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    task = TaskLoader().load(args.task)
    adapter = ArenaAdapter(task)

    trials = []
    for axis in (3, 4, 5):
        for sign in (1.0, -1.0):
            for mag in args.magnitudes:
                trial = _run_trial(adapter, axis, sign, mag, args.steps)
                trials.append(trial)
                print(json.dumps(trial, indent=2, default=str))
                # Persist per-trial trace.
                if _TRACE_PATH.exists():
                    stamped = args.out_dir / f"trace_rot_axis{axis}_sign{sign:.0f}_mag{mag:.2f}_{int(time.time())}.jsonl"
                    shutil.copy(_TRACE_PATH, stamped)

    summary = {
        "task": args.task,
        "steps": args.steps,
        "magnitudes": args.magnitudes,
        "trials": trials,
    }
    out_path = args.out_dir / f"rotational_calibration_{int(time.time())}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSummary written to {out_path}")


if __name__ == "__main__":
    main()
