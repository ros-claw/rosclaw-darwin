# Cross-Task Transfer Status v2 Report

## 1. Updated task roles

| task | role |
|---|---|
| `lift_object` | primary single-task evolution evidence |
| `pick_object` | saturated sanity / task-aware metric regression check |
| `goal_pose_lift_only` / `goal_pose_lift_hold` | progressive transfer diagnosis subtasks |
| `goal_pose_lift_small_yaw` / `goal_pose_lift_90_yaw` / `goal_pose_full` | final hard tasks |

---

## 2. Transfer level definitions

| level | definition |
|---|---|
| Level 0 | hint consumed but no measurable improvement |
| Level 1 | progress / residual / phase boundary improves |
| Level 2 | hint improves success on a decomposed subtask |
| Level 3 | hint improves success on the full task |
| Level 4 | same recipe improves at least two tasks or task families |

---

## 3. Current status

| task | condition | outcome | transfer level |
|---|---|---|---|
| `lift_object` | auto hints vs. no hints | progress trend positive but not yet statistically significant | **Level 1** |
| `pick_object` | manual / auto hints | success_rate = 1.0 (saturated) | **Level 3** (regression sanity, not transfer gain) |
| `goal_pose_lift_only` | with manual grasp-stability hints | subtask_success = true | **Level 2** |
| `goal_pose_lift_hold` | with manual grasp-stability hints | subtask_success = true | **Level 2** |
| `goal_pose_lift_small_yaw` | with manual grasp-stability hints | subtask_success = false (pose_ok false) | **Level 0** |
| `goal_pose_lift_90_yaw` | with manual grasp-stability hints | subtask_success = false | **Level 0** |
| `goal_pose_full` | with manual grasp-stability hints | success_rate = 0.0 | **Level 0** |

---

## 4. Validated transferable skills

**None.**

No single recipe has been shown to improve success on two distinct tasks or
task families.  The grasp-stability hints help `goal_pose` lift subtasks but do
not solve reorientation.

---

## 5. Candidate recipes

| recipe | trigger | evidence |
|---|---|---|
| `unstable_grasp_recipe` | `lifted_then_dropped`, `unstable_grasp` | Improves progress and held duration on `goal_pose` lift subtasks. |
| `blocked_gripper_normal_recipe` | `blocked_gripper_normal` | Corrects the gripper-pos threshold assumption; may transfer to any cube-grasp task. |
| `yaw_not_transferred_recipe` | `yaw_not_transferred_to_object` | Experimental; depends on finding a working orientation-control path. |

---

## 6. Local adaptive hints

Most consumed hints on `goal_pose` are local adaptive hints that react to the
specific trace but do not transfer:

- `orientation_aware_grasp`
- `two_stage_reorientation`
- `lower_lift_acceleration`
- `stabilize_lift`
- `longer_gripper_close`

They improve progress but do not solve the reorientation bottleneck.

---

## 7. Honest claim status

**Cannot claim:**

```text
Universal cross-task transfer proven.
Grasp-stability hints are validated transferable skills.
goal_pose solved.
```

**Can claim:**

```text
The failure-to-hint pipeline now distinguishes subtask-level transfer
(level 2) from full-task transfer (level 3) and validates that no
validated transferable skill exists yet.
```

---

## 8. Next step

Find a working end-effector yaw-control mechanism.  Once reorientation is
achieved, retest the candidate recipes on both `goal_pose` and `lift_object`
to see if any become Level-4 transferable skills.
