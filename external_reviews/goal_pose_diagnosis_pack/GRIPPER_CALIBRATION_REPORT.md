# Gripper Calibration Report

## 1. Purpose

The previous diagnostic assumed that a `gripper_pos` of ~0.024 meant the
gripper could not close any tighter.  That inference is unsafe: a gripper
holding a cube is *supposed* to stop at roughly the cube thickness.  This
calibration separates three hypotheses:

1. The gripper can close fully in free air (joint / controller limit).
2. The gripper stops at ~0.024 only when the cube is between the fingers
   (geometric blocked closure).
3. Stronger close commands overcome the blockage, possibly by pushing the cube
   out of the way (force / contact limit).

---

## 2. Calibration setup

- Task: `configs/tasks/goal_pose.yaml` (`cube_goal_pose` environment).
- Robot: `franka_ik` in relative mode.
- Policy: `GripperCalibrationPolicy` (`heuristic_policy.GripperCalibrationPolicy`).
- Trace directory: `/tmp/rosclaw_data/traces/episode_trace.jsonl`.
- Output directory: `/tmp/rosclaw_data/calibrations/`.

### Empty-close scenario

The end-effector remains at its initial pose and the gripper is commanded to
close for 100 steps.  No object blocks the fingers.

### Blocked-close scenario

The policy servos above the cube, descends to grasp height, and commands the
gripper to close for 100 steps while the cube is between the fingers.

### Close commands tested

- `-0.3`
- `-0.6`
- `-1.0`

---

## 3. Commands

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH

python scripts/diagnostics/run_gripper_empty_close_calibration.py \
  --close-command -0.3 --close-command -0.6 --close-command -1.0 \
  --close-steps 100 --out-dir /tmp/rosclaw_data/calibrations/empty_close

python scripts/diagnostics/run_gripper_blocked_close_calibration.py \
  --close-command -0.3 --close-command -0.6 --close-command -1.0 \
  --close-steps 100 --out-dir /tmp/rosclaw_data/calibrations/blocked_close_v2
```

---

## 4. Results

### Empty close (no object)

| close command | min gripper_pos | final gripper_pos | interpretation |
|---|---|---|---|
| -0.3 | 0.000118 | 0.000118 | fully closed |
| -0.6 | 0.000118 | 0.000118 | fully closed |
| -1.0 | 0.000119 | 0.000120 | fully closed |

**Result:** The gripper can close to essentially zero open width when nothing is
in the way.  There is no joint limit or controller limit near 0.024.

### Blocked close (cube between fingers)

| close command | min gripper_pos | final object_z | interpretation |
|---|---|---|---|
| -0.3 | **0.02405** | 0.217 | blocked by cube; cannot generate enough force to close tighter |
| -0.6 | 0.000118 | 0.021 | gripper closes fully; cube is pushed aside / drops |
| -1.0 | 0.000118 | 0.021 | gripper closes fully; cube is pushed aside / drops |

Raw result files:

```text
/tmp/rosclaw_data/calibrations/empty_close/empty_close_calibration_1781511829.json
/tmp/rosclaw_data/calibrations/blocked_close_v2/blocked_close_calibration_1781512274.json
```

---

## 5. Interpretation

| observation | conclusion |
|---|---|
| empty close < 0.001 | Gripper joint/controller can reach essentially zero open width. |
| blocked close at -0.3 ≈ 0.024 | 0.024 is the normal geometric blocked closure when the cube is held with moderate force. |
| blocked close at -0.6 / -1.0 < 0.001 | Higher close command overcomes the blockage, but the cube is no longer stably held (it falls back to the table). |
| `gripper_close_threshold = 0.0096` | **Too strict.** A cube held between fingers will naturally read ~0.024. |

The previous failure should not be read as "gripper cannot close."  It should
be read as:

```text
The gripper can close tightly, but the contact/friction between the fingers
and the cube at ~0.024 open width is insufficient to lift + reorient the cube.
```

This shifts the bottleneck from *closure capability* to *grasp stability*:
contact geometry, friction, squeeze force, and lift/reorientation dynamics.

---

## 6. New grasp-stability metric

`rosclaw_darwin/evaluation/grasp_metrics.py` now provides
`infer_grasp_stability` based on:

- `object_lifted`: object height delta >= threshold
- `object_follows_eef`: mean/max object-eef distance after lift start
- `held_duration_steps`: steps the object stays elevated
- `drop_detected`: object falls from peak by more than threshold
- `grasp_stability_score`: composite in [0, 1]

The policy no longer uses `gripper_pos < 0.0096` as the sole grasp-success
proxy.

---

## 7. Implications for policy v3

1. Do not wait for `gripper_pos < 0.0096` before lifting; ~0.024 is the
   realistic blocked-closure width for this cube.
2. Focus on increasing contact stability at that width: lower lift
   acceleration, smaller reorientation steps, longer squeeze.
3. If stronger close commands push the cube out, policy v3 should maintain
   the cube between fingers while closing, rather than increasing close force
   blindly.
4. Consider a side / face-centered grasp to increase finger-cube contact area.

---

## 8. Answers to the outline questions

1. **Empty minimum gripper_pos:** ~0.00012 (essentially closed).
2. **Cube-blocked minimum gripper_pos:** ~0.024 at -0.3 command; <0.001 at
   -0.6 / -1.0 commands.
3. **Is 0.024 normal?** Yes, for a moderate close command with the cube held
   between the fingers.
4. **Is the current gripper_close_threshold wrong?** Yes.  Expecting <0.0096
   is unrealistic for a held cube.
5. **New grasp stability metric:** object lift, object-eef following,
   held duration, drop detection (see `grasp_metrics.py`).

---

## 9. Next step

Run rotational action calibration to determine which `action[..., 3:6]` axis
controls end-effector yaw and whether the object yaw follows.
