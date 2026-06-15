# Goal Pose Grasp Stability Metrics v3 Report

## 1. Purpose

Replace the naive ``gripper_pos < 0.0096`` grasp-success proxy with
object-centric metrics.  This report analyzes a fresh 2500-step goal_pose trace
taken with the v2 schema and the new ``grasp_metrics.py`` module.

---

## 2. Trace

- Command:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_trace.py
```

- Output: `/tmp/rosclaw_data/traces/goal_pose_trace_1781513423.jsonl`
- Steps: 2500
- Manual hints: `orientation_aware_grasp`, `two_stage_reorientation`,
  `lower_lift_acceleration`, `stabilize_lift`, `longer_gripper_close`

---

## 3. Phase timeline

| phase | steps |
|---|---|
| APPROACH | 74 |
| PRE_GRASP_ORIENT | 30 |
| DESCEND | 10 |
| GRASP | 75 |
| LIFT | 50 |
| REORIENT | 401 |
| HOLD | 1860 |

---

## 4. Key metrics

```json
{
  "object_lifted": true,
  "object_follows_eef": true,
  "held_duration_steps": 869,
  "drop_detected": true,
  "drop_step": 912,
  "object_height_peak": 0.330,
  "object_height_final": 0.113,
  "object_height_drop_after_peak": 0.217,
  "relative_object_eef_distance_mean": 0.0048,
  "relative_object_eef_distance_max": 0.0048,
  "grasp_stability_score": 0.65
}
```

- **Gripper min:** 0.0240 (normal blocked closure on a cube).
- **Object height peak:** 0.330 m.
- **Drop:** object fell from 0.330 m to 0.113 m after step 912.
- **Object-follows-eef:** True — the cube stays very close to the end-effector
  (mean distance 4.8 mm), so the grasp is geometrically engaged.

---

## 5. End-effector yaw vs. object yaw

| step | phase | eef_yaw | object_yaw | object_yaw_error |
|---|---|---:|---:|---:|
| 0 | APPROACH | 0.000 | 0.000 | 1.571 |
| 500 | REORIENT | 0.000 | 0.268 | 1.303 |
| 1000 | HOLD | 0.000 | 0.504 | 1.066 |
| 1500 | HOLD | 0.000 | 0.686 | 0.884 |
| 2000 | HOLD | 0.000 | 0.832 | 0.739 |

**Critical finding:** `eef_yaw` did not change at all.  The object yaw changed
because the cube slipped/rotated inside the gripper, not because the gripper
itself rotated.  This confirms the rotational-calibration result that
`action[..., 5]` does not control end-effector yaw.

---

## 6. Failure signature v3 tags

From this trace we can assign:

- `grasp_established` — object was lifted and followed the eef.
- `object_follows_eef` — mean object-eef distance < 1 cm.
- `lifted_but_slipped` — object reached 0.33 m and then fell.
- `rotation_induced_slip` — drop occurred during/after REORIENT while the cube
  was passively rotating inside the gripper.
- `hold_instability` — object continued to lose height during HOLD.
- `yaw_not_transferred_to_object` — eef yaw remained 0 while object yaw
  changed.
- `blocked_gripper_normal` — gripper stopped at ~0.024, which is the normal
  geometric width when holding the cube.

---

## 7. Answers to outline questions

1. **Object follows eef?** Yes, mean distance 4.8 mm.
2. **Drop phase?** Drop began at step 912, during HOLD after REORIENT.
3. **Drop related to reorientation?** Yes; the cube was passively rotating
   inside the gripper during REORIENT/HOLD and gradually slipped down.
4. **gripper_pos 0.024 normal or abnormal?** Normal blocked closure.
5. **How do new signatures guide intervention?** The bottleneck is not
   reaching or initial grasp; it is maintaining contact during passive
   rotation.  Policy v3 must either (a) rotate the eef via quaternion targets,
   or (b) prevent slip by increasing contact stability/friction, or (c) avoid
   large reorientation torques.

---

## 8. Conclusion

The object is successfully lifted and closely follows the end-effector, but it
slips and rotates inside the gripper.  The gripper closure width (~0.024) is
not the problem; the problem is that the end-effector cannot actively reorient
the cube because the relative-mode rotational action has no authority.

The next sprint must test whether commanding a target quaternion in
`action[..., 3:7]` produces controlled end-effector rotation, and whether the
object then follows that rotation without slipping.
