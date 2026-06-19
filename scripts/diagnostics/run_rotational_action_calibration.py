#!/usr/bin/env python3
"""Rotational action calibration for franka_ik relative mode.

Sweeps action[..., 3], action[..., 4], action[..., 5] and records the
resulting end-effector roll/pitch/yaw deltas.
"""

from __future__ import annotations

import argparse
import json
import math
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


def _angle_diff(target: float, current: float) -> float:
    """Smallest signed angle from current to target, wrapped to [-pi, pi]."""
    diff = target - current
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return diff


_JOINT_NAMES = {4: "panda_joint5", 5: "panda_joint6", 6: "panda_joint7"}


def _run_trial(adapter, axis, sign, magnitude, steps, use_quaternion=False, target_yaw_delta=0.785398):
    if _TRACE_PATH.exists():
        _TRACE_PATH.unlink()

    policy_config = {
        "policy_type": "rotational_calibration",
        "policy_config_dict": {
            "calibration_axis": axis,
            "calibration_sign": sign,
            "calibration_magnitude": magnitude,
            "calibration_steps": steps,
            "use_quaternion_target": use_quaternion,
            "target_yaw_delta": target_yaw_delta,
        },
    }
    arena_result = adapter.run_policy(policy_config, episodes=1, max_steps=steps)
    trace = _read_trace()
    valid_trace = [t for t in trace if t.get("eef_roll") is not None]
    if len(valid_trace) < 2:
        return {"error": "insufficient valid trace", "status": arena_result.status}

    initial = valid_trace[0]
    final = valid_trace[-1]
    def _delta(final_val, initial_val, wrap=False):
        if final_val is None or initial_val is None:
            return None
        if wrap:
            return _angle_diff(final_val, initial_val)
        return final_val - initial_val
    return {
        "axis_index": axis,
        "axis_name": _AXIS_NAMES[axis],
        "sign": sign,
        "magnitude": magnitude,
        "steps": steps,
        "use_quaternion_target": use_quaternion,
        "target_yaw_delta": target_yaw_delta,
        "action_dim": final.get("action_dim"),
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
            "roll": _delta(final.get("eef_roll"), initial.get("eef_roll"), wrap=True),
            "pitch": _delta(final.get("eef_pitch"), initial.get("eef_pitch"), wrap=True),
            "yaw": _delta(final.get("eef_yaw"), initial.get("eef_yaw"), wrap=True),
        },
        "delta_pos": {
            "x": _delta(final.get("eef_x"), initial.get("eef_x")),
            "y": _delta(final.get("eef_y"), initial.get("eef_y")),
            "z": _delta(final.get("eef_z"), initial.get("eef_z")),
        },
    }


def _run_joint_space_trial(adapter, joint_index, command_value, steps):
    if _TRACE_PATH.exists():
        _TRACE_PATH.unlink()

    policy_config = {
        "policy_type": "joint_space_calibration",
        "policy_config_dict": {
            "joint_index": joint_index,
            "command_value": command_value,
            "calibration_steps": steps,
            "gripper_open": True,
        },
    }
    arena_result = adapter.run_policy(policy_config, episodes=1, max_steps=steps)
    trace = _read_trace()
    valid_trace = [t for t in trace if t.get("eef_roll") is not None]
    if len(valid_trace) < 2:
        return {"error": "insufficient valid trace", "status": arena_result.status}

    initial = valid_trace[0]
    final = valid_trace[-1]
    def _delta(final_val, initial_val, wrap=False):
        if final_val is None or initial_val is None:
            return None
        if wrap:
            return _angle_diff(final_val, initial_val)
        return final_val - initial_val
    return {
        "joint_index": joint_index,
        "joint_name": _JOINT_NAMES.get(joint_index, f"panda_joint{joint_index + 1}"),
        "command_value": command_value,
        "target_delta_rad": 0.5 * command_value,
        "steps": steps,
        "action_dim": final.get("action_dim"),
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
            "roll": _delta(final.get("eef_roll"), initial.get("eef_roll"), wrap=True),
            "pitch": _delta(final.get("eef_pitch"), initial.get("eef_pitch"), wrap=True),
            "yaw": _delta(final.get("eef_yaw"), initial.get("eef_yaw"), wrap=True),
        },
        "delta_pos": {
            "x": _delta(final.get("eef_x"), initial.get("eef_x")),
            "y": _delta(final.get("eef_y"), initial.get("eef_y")),
            "z": _delta(final.get("eef_z"), initial.get("eef_z")),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotational action calibration")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--magnitudes", type=float, nargs="+", default=[0.5, 1.0])
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/rosclaw_data/calibrations"))
    parser.add_argument(
        "--embodiment",
        type=str,
        default=None,
        help="Override Arena embodiment (e.g., franka_ik, franka_joint_pos).",
    )
    parser.add_argument(
        "--absolute-mode",
        action="store_true",
        help="Test absolute quaternion targets instead of relative action[3:6] commands.",
    )
    parser.add_argument(
        "--target-yaw-delta",
        type=float,
        default=0.785398,
        help="Target yaw rotation in radians for quaternion mode (default: 45 deg).",
    )
    parser.add_argument(
        "--joint-indices",
        type=int,
        nargs="+",
        default=[4, 5, 6],
        help="Wrist joint indices to test in joint-space mode (default: 4 5 6).",
    )
    parser.add_argument(
        "--command-values",
        type=float,
        nargs="+",
        default=[0.4, 0.8],
        help="Joint-space command values to test (default: 0.4 0.8).",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    task = TaskLoader().load(args.task)
    if args.embodiment is not None:
        task.metadata.setdefault("arena_env_args", {})
        task.metadata["arena_env_args"]["embodiment"] = args.embodiment
    adapter = ArenaAdapter(task)

    trials = []
    is_joint_space = args.embodiment == "franka_joint_pos"

    if is_joint_space:
        for joint_index in args.joint_indices:
            for command_value in args.command_values:
                trial = _run_joint_space_trial(adapter, joint_index, command_value, args.steps)
                trials.append(trial)
                print(json.dumps(trial, indent=2, default=str))
                if _TRACE_PATH.exists():
                    stamped = args.out_dir / f"trace_joint{joint_index}_cmd{command_value:.2f}_{int(time.time())}.jsonl"
                    shutil.copy(_TRACE_PATH, stamped)
    elif args.absolute_mode:
        trial = _run_trial(
            adapter,
            axis=5,
            sign=1.0,
            magnitude=0.0,
            steps=args.steps,
            use_quaternion=True,
            target_yaw_delta=args.target_yaw_delta,
        )
        trials.append(trial)
        print(json.dumps(trial, indent=2, default=str))
        if _TRACE_PATH.exists():
            stamped = args.out_dir / f"trace_rot_quaternion_{int(time.time())}.jsonl"
            shutil.copy(_TRACE_PATH, stamped)
    else:
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
        "embodiment": args.embodiment,
        "absolute_mode": args.absolute_mode,
        "target_yaw_delta": args.target_yaw_delta,
        "joint_indices": args.joint_indices if is_joint_space else None,
        "command_values": args.command_values if is_joint_space else None,
        "trials": trials,
    }
    out_path = args.out_dir / f"rotational_calibration_{int(time.time())}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSummary written to {out_path}")


if __name__ == "__main__":
    main()
