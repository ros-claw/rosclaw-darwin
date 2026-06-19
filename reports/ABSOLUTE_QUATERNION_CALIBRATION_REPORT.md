# Absolute Quaternion Orientation Calibration Report

> **Correction (2026-06-16):** The zero-rotation conclusion in the original
> version of this report was caused by a sensor-reading bug.  The policy was
> reading `source_quat_w` (robot-base orientation) instead of `quat_w`
> (end-effector orientation).  With the patched `franka_ik_abs` embodiment
> (`action_dim = 8`), absolute quaternion commands produce a yaw change close
> to the 0.785 rad target.  See
> [Franka IK Orientation Investigation Report](FRANKA_IK_ORIENTATION_INVESTIGATION_REPORT.md)
> for the corrected analysis.

## 1. Purpose

Test whether commanding an absolute target quaternion via `action[..., 3:7]`
produces controlled end-effector rotation in the current `franka_ik` absolute
pose mode.

## 2. Setup

- Task: `configs/tasks/goal_pose.yaml`
- Robot: `franka_ik`
- Policy: `RotationalCalibrationPolicy` with `use_quaternion_target=True`
- Target yaw delta: `0.785398 rad` (45°)
- Steps per trial: `30`
- Command:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_rotational_action_calibration.py \
  --absolute-mode --steps 30 --target-yaw-delta 0.785398 \
  --out-dir /tmp/rosclaw_data/calibrations/rotational_absolute
```

## 3. Results

| metric | value |
|---|---|
| action_dim | **7** |
| Δ roll | 0.0 |
| Δ pitch | 0.0 |
| Δ yaw | **0.0** |
| Δ position | ~6e-8 m (negligible) |

The action space is only **7-dimensional** (3 position + 3 rotation + 1 gripper),
so writing a 4-component quaternion to `action[..., 3:7]` would overwrite the
single gripper channel.  Even if the controller were to interpret the 3
orientation channels as a quaternion, no end-effector rotation was observed.

## 4. Interpretation

| question | answer |
|---|---|
| Does absolute quaternion target via `action[..., 3:7]` rotate the eef? | **No.** |
| Is the action space large enough for a full pose target + gripper? | **No** — it is 7-dimensional. |
| Is `franka_ik` in this configuration capable of orientation control? | **Not via the current action interface.** |

This means:

- The `HeuristicServoGoalPosePolicy` `_apply_orientation_quaternion` fallback
  cannot work with the current 7-dim action space.
- The v3 policy's decision to disable yaw-dependent phases (`skip_broken_yaw`)
  is validated: there is currently **no working orientation-control channel**.
- Solving `goal_pose` requires either:
  1. A different embodiment or controller configuration with an 8-dim action
     space and working orientation targets, or
  2. External guidance from the Arena team on how to command eef yaw.

## 5. Next Step

The P0 controller question is now even sharper:

> How is end-effector orientation supposed to be commanded in the Arena
> `franka_ik` setup, given that the action space is 7-dimensional and neither
> `action[..., 5]` nor `action[..., 3:7]` produces any rotation?

See `reports/ARENA_ISSUE_TRACKER.md` for the consolidated question list.

## 6. Files Changed

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `scripts/diagnostics/run_rotational_action_calibration.py`
- `reports/ARENA_ISSUE_TRACKER.md`
