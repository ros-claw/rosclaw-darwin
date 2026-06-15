# Rotational Action Calibration Report

## 1. Purpose

The goal_pose policy assumed that `action[..., 5]` controls end-effector yaw in
`franka_ik` relative mode.  The previous report could not prove whether yaw was
actually changing because the trace only recorded object yaw, not end-effector
yaw.  This sprint calibrates `action[..., 3:6]` directly.

---

## 2. Setup

- Task: `configs/tasks/goal_pose.yaml`
- Robot: `franka_ik`
- Policy: `RotationalCalibrationPolicy`
- Axes tested: `action[..., 3]` (rot_x), `action[..., 4]` (rot_y), `action[..., 5]` (rot_z)
- Signs: `+` and `-`
- Magnitudes: `0.5`, `1.0`
- Steps per trial: `30`
- Trace: `/tmp/rosclaw_data/traces/episode_trace.jsonl`
- Result: `/tmp/rosclaw_data/calibrations/rotational/rotational_calibration_1781513111.json`

Command:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_rotational_action_calibration.py \
  --steps 30 --magnitudes 0.5 1.0 \
  --out-dir /tmp/rosclaw_data/calibrations/rotational
```

---

## 3. Results

For every combination of axis, sign, and magnitude, the end-effector
roll/pitch/yaw **did not change**:

| axis | sign | magnitude | Δ roll | Δ pitch | Δ yaw |
|---|---|---:|---:|---:|---:|
| rot_x | + | 0.5 | 0.0 | 0.0 | 0.0 |
| rot_x | + | 1.0 | 0.0 | 0.0 | 0.0 |
| rot_x | - | 0.5 | 0.0 | 0.0 | 0.0 |
| rot_x | - | 1.0 | 0.0 | 0.0 | 0.0 |
| rot_y | + | 0.5 | 0.0 | 0.0 | 0.0 |
| rot_y | + | 1.0 | 0.0 | 0.0 | 0.0 |
| rot_y | - | 0.5 | 0.0 | 0.0 | 0.0 |
| rot_y | - | 1.0 | 0.0 | 0.0 | 0.0 |
| rot_z | + | 0.5 | 0.0 | 0.0 | 0.0 |
| rot_z | + | 1.0 | 0.0 | 0.0 | 0.0 |
| rot_z | - | 0.5 | 0.0 | 0.0 | 0.0 |
| rot_z | - | 1.0 | 0.0 | 0.0 | 0.0 |

However, the rotational commands **did produce translational motion**:

- `rot_x` moved the end-effector primarily in ±y and z.
- `rot_y` moved the end-effector primarily in ±x and z.
- `rot_z` produced only tiny positional drift.

This indicates that the `franka_ik` controller in this configuration does **not**
interpret `action[..., 3:6]` as end-effector rotational deltas.

---

## 4. Interpretation

| question | answer |
|---|---|
| Does `action[..., 3]` control roll? | No. It causes lateral translation. |
| Does `action[..., 4]` control pitch? | No. It causes longitudinal translation. |
| Does `action[..., 5]` control yaw? | No. It has almost no effect. |
| Is `PRE_GRASP_ORIENT` via `action[..., 5]` effective? | No. |
| How can yaw be controlled? | By commanding the target **quaternion** in `action[..., 3:7]` if the controller is in absolute mode, or by another controller configuration. |

Consequences:

- The previous `PRE_GRASP_ORIENT` phase, which issued `action[..., 5] = yaw_err`,
  could not rotate the gripper.
- The `REORIENT` phase used `_apply_orientation`, which in relative mode also
  wrote `action[..., 5]`.  Any observed object yaw change in that phase was
  caused by contact/slipping, not by controlled end-effector rotation.
- Policy v3 must **stop relying on `action[..., 5]` for yaw** and instead
  command an explicit target quaternion.

---

## 5. Method note

Each trial ran for 30 steps with a constant rotational command.  The
end-effector orientation was read from `ee_frame.data.source_quat_w` and
converted to roll/pitch/yaw using the same convention as the policy
(`_quat_to_rpy`).  Initial and final orientations were compared; all trials
returned zero angular displacement.

---

## 6. Next step

Test whether setting `action[..., 3:7]` to a target quaternion produces
controlled end-effector rotation.  If it does, reimplement `PRE_GRASP_ORIENT`
and `REORIENT` to use quaternion targets instead of relative yaw commands.
If it does not, the embodiment/controller configuration does not support
explicit orientation control and the task may require a different controller
or a learned policy.
