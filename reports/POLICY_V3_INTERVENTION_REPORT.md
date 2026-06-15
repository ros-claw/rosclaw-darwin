# Goal Pose Policy v3 Intervention Report

## 1. Motivation

The v1.3 diagnosis concluded that `franka_ik` relative-mode rotational actions
(`action[..., 3:6]`) produce no measurable end-effector rotation.  Policy v3 was
designed to make progress **without relying on broken yaw control**, while
keeping the code ready to exploit yaw once the controller/embodiment is fixed.

## 2. Changes from v2 to v3

### 2.1 New state: `VERIFY_OBJECT_FOLLOWING`

Inserted between `LIFT` and `ALIGN`/`REORIENT`.

- Holds the gripper closed for a short pause (default 5 steps).
- Checks whether the object moves with the end-effector and whether the
  relative object-eef distance stays below a threshold.
- If the object does not follow, transitions directly to `HOLD` and records
  `object_not_following_eef` in the trace.

### 2.2 Broken-yaw guard: `skip_broken_yaw_control`

A new config flag (default `false`) that, when enabled:

- disables active yaw commands in `PRE_GRASP_ORIENT` (keeps the phase as a
  settling pause);
- skips `REORIENT`;
- disables `require_orientation_alignment` in `ALIGN`.

### 2.3 New state: `STABILIZE`

Available after `REORIENT` for future use.  Holds position with minimal motion
for `stabilize_steps_after_yaw` steps.

### 2.4 Quaternion orientation fallback

`_apply_orientation` now supports `use_quaternion_orientation_target`.  When
the action space has at least 7 dims, it computes a delta quaternion from
current eef orientation toward the target, clamps the rotation angle to
`yaw_step_size`, and writes it to `action[..., 3:7]`.

### 2.5 v3 recipe parameter consumption

`HeuristicServoGoalPosePolicy` now consumes:

- `yaw_step_size`
- `stabilize_steps_after_yaw`
- `verify_object_following_steps`
- `object_following_distance_threshold`
- `use_quaternion_orientation_target`

and maps the new hints:

- `skip_broken_yaw`
- `verify_object_following`
- `incremental_yaw_reorientation`
- `stabilize_after_rotation`

## 3. Config

`configs/policies/heuristic_servo_goal_pose_v3.yaml` enables the broken-yaw
path while preserving a settling pause above the object:

```yaml
pre_grasp_orient: true
reorient_before_align: false
require_orientation_alignment: false
skip_broken_yaw_control: true
verify_object_following_steps: 5
```

## 4. Single-episode trace results

Run with:

```bash
export ROSCLAW_ARENA_MODE=docker
python -c "
from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader
import yaml
from pathlib import Path

task = TaskLoader().load('configs/tasks/goal_pose.yaml')
with open('configs/policies/heuristic_servo_goal_pose_v3.yaml') as f:
    policy = yaml.safe_load(f)
policy.setdefault('policy_id', 'heuristic_servo_goal_pose_v3')
result = ArenaAdapter(task).run_policy(policy, episodes=1)
print(result.metrics)
"
```

| metric | baseline v2 | v3 |
|---|---|---|
| success_rate | 0.0 | 0.0 |
| progress | 0.4982 | 0.4985 |
| object_height_max | 0.332 m | 0.286 m |
| held until step | ~200 | ~1829 |
| final object_z | 0.190 m | 0.039 m |
| gripper_pos_min | 0.0244 | 0.0240 |

The v3 policy held the object **~9× longer** than the baseline.  Both runs
failed because the object eventually slipped and because `pose_reached` still
requires orientation alignment.

## 5. Failure mode observed

**Long-duration hold instability.**  After reaching a stable hold at
`object_z ≈ 0.286 m`, the cube gradually slipped out of the gripper over
~1600 steps, even though `gripper_pos` remained at the normal blocked-closure
value (~0.024 m).  This suggests that sustained grasp force / contact friction,
rather than initial closure, is the next physical bottleneck once yaw is fixed.

## 6. Honest conclusion

- **goal_pose is not solved.**
- **Controller yaw authority remains the primary blocker.**
- **v3 produced a real, measurable improvement in hold duration**, validating
  the value of disabling the broken yaw path and adding object-following
  verification.
- **Next step:** consult the Arena team about correct orientation control, then
  re-run subtask decomposition and v3 ablation.

## 7. Files changed

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `configs/policies/heuristic_servo_goal_pose_v3.yaml`
- `reports/FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md`
- `reports/POLICY_V3_INTERVENTION_REPORT.md`
