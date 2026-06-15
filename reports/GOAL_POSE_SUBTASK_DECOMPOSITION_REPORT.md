# Goal Pose Subtask Decomposition Report

## 1. Purpose

Decompose `goal_pose` into simpler subtasks to locate the first failing
physical boundary.

---

## 2. Subtask definitions

| task | success condition | purpose |
|---|---|---|
| `goal_pose_lift_only` | object_z > 0.2 | verify basic grasp + lift |
| `goal_pose_lift_hold` | object_z > 0.2 | verify lift can be maintained |
| `goal_pose_lift_small_yaw` | object_z > 0.2 and min yaw error < 0.5 rad | verify small reorientation |
| `goal_pose_lift_90_yaw` | object_z > 0.2 and min yaw error < 0.2 rad | verify full 90° reorientation |
| `goal_pose` (full) | object_z > 0.2 and yaw error < 0.2 rad | original task |

All subtasks use the same `heuristic_servo_goal_pose` policy with manual
grasp-stability hints.

---

## 3. Command

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_subtask_decomposition.py \
  --out-dir /tmp/rosclaw_data/subtasks
```

Result file: `/tmp/rosclaw_data/subtasks/subtask_decomposition_1781514624.json`

---

## 4. Results

| task | subtask_success | object_lifted | object_peak | pose_ok | min yaw_error |
|---|---|---|---|---:|---:|
| `goal_pose_lift_only` | **true** | true | 0.332 | true (no yaw req) | — |
| `goal_pose_lift_hold` | **true** | true | 0.332 | true (no yaw req) | — |
| `goal_pose_lift_small_yaw` | false | true | 0.331 | false | 1.07 |
| `goal_pose_lift_90_yaw` | false | true | 0.326 | false | 1.28 |
| `goal_pose` (full) | false | true | 0.332 | false | 1.08 |

(The min yaw_error reported for yaw-requiring subtasks is the *absolute minimum*
observed during the episode; the final yaw_error is similar because the cube
passively slips/rotates and then settles.)

---

## 5. Failure boundary

```text
lift_only  OK
lift_hold  OK
lift_small_yaw  FAIL  <- first failing boundary
lift_90_yaw  FAIL
full  FAIL
```

The first failing subtask is **reorientation / yaw alignment**.  The policy
can lift and hold the cube, but it cannot actively change the cube's yaw.

---

## 6. Root cause

The Rotational Action Calibration Report showed that `action[..., 3:6]` have
zero authority over end-effector orientation in this `franka_ik`
configuration.  Therefore:

- `PRE_GRASP_ORIENT` cannot align gripper fingers to stable grasp faces.
- `REORIENT` cannot actively rotate the cube toward the target yaw.
- The observed object yaw changes are passive slipping inside the gripper.

The failure boundary is **not** grasp establishment, lift, or hold stability;
it is **controlled reorientation**.

---

## 7. Implications for policy v3

1. Do not rely on `action[..., 5]` for yaw.
2. Test whether `action[..., 3:7]` can be used to command a target
   quaternion.
3. If quaternion commands work, implement `PRE_GRASP_ORIENT` and `REORIENT`
   via target quaternion.
4. If quaternion commands do not work, the task requires a different
   controller or embodiment.

---

## 8. Claim update

We can now claim:

```text
Darwin decomposed goal_pose into lift-only, lift-hold, and yaw-reorientation
subtasks and identified that the first failing boundary is controlled
reorientation, not grasp or lift.
```

We still cannot claim:

```text
goal_pose solved.
reorientation hints are validated transferable skills.
```
