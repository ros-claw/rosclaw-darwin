# Pick Object Success Gap Report

## 1. Observation

The original `heuristic_servo_pick` policy achieved very high progress on
`pick_object_001` but zero success in our internal metric:

```text
without_hints: progress = 0.9533, success_rate = 0.0
manual_hints:  progress = 0.9251, success_rate = 0.0
auto_hints:    progress = 0.9335, success_rate = 0.0
```

All failures were classified as ``target_not_reached_after_lift`` by the
generic Arena-side progress metric.

## 2. Root cause: metric mismatch

The ROSClaw task definition for `pick_object_001` specifies:

```yaml
eval:
  success_conditions: [object_lifted]
```

The generic metric inside the Arena container, however, required **both**
`object_lifted` **and** `object_to_target_distance_min < threshold`.  The
policy was lifting the cube, but the extra target-proximity check caused every
episode to be recorded as a failure even though the environment itself had
already terminated with success (Arena jobmetric success_rate = 1.0).

## 3. Intervention: task-aware success metric

Two changes fixed the gap.

### 3.1 Arena-side metric now reads `success_conditions`

`ArenaAdapter.run_policy` now forwards the task's `success_conditions` to the
Docker job config:

```python
job["success_conditions"] = list(self.task.eval.success_conditions or [])
```

`run_eval.py` consumes this and relaxes the success check when the task only
requires `object_lifted`:

```python
if require_object_lifted and not require_target_proximity:
    success = reached_object and lifted
else:
    success = reached_object and lifted and target_min < success_threshold
```

### 3.2 Pick policy LIFT target corrected

`HeuristicServoPickPolicy.LIFT` previously added `lift_height` on top of the
command `target_pos`, which could overshoot the desired height.  It now uses
`target_pos` directly (matching `HeuristicServoLiftPolicy`) and only falls back
to `object_pos + lift_height` when no command target is available.

## 4. Updated ablation

A fresh 10-episode ablation was run with the corrected policy and metric:

```bash
python scripts/ablations/run_lift_skill_hint_ablation.py \
  --task configs/tasks/pick_object.yaml \
  --policy configs/policies/heuristic_servo_pick.yaml \
  --manual-hints precision_target_tracking,slow_final_align,hold_at_target \
  --episodes 10 \
  --out /tmp/rosclaw_data/ablations/pick_object_task_aware_v1 \
  --report-path reports/PICK_OBJECT_SKILL_HINT_ABLATION_REPORT.md
```

Results:

| condition | success_rate | progress | object_height_delta | failure_counts |
|---|---|---|---|---|
| without_hints | **1.0000** | 0.9561 | 0.3059 | ``unknown_failure``: 0 |
| manual_hints | **1.0000** | 0.9539 | 0.2991 | ``unknown_failure``: 0 |
| auto_hints | **1.0000** | 0.9472 | 0.3020 | ``unknown_failure``: 0 |

All conditions now achieve **100% success** on `pick_object_001` because the
policy reliably lifts the cube and the metric matches the task definition.

## 5. Transfer / hint value on this task

Because the base policy already solves the task, the manual and auto hints do
not raise success further.  Their effect is now visible on secondary metrics:

- Manual hints slightly reduce object lift height / progress (more conservative
  alignment behaviour).
- Auto hints are empty here (no failures in the without-hints Loop 1, so the
  failure-to-hint engine has nothing to generate).

This means `pick_object` is no longer a useful testbed for *success-transfer*
claims; it becomes a **sanity-check** that the cross-task pipeline can run a
pick-style task end-to-end.

## 6. Honest conclusion

- The `pick_object_001` success gap was **a metric-artifact**, not a policy
  capability gap.
- `HeuristicServoPickPolicy` correctly grasps and lifts the cube.
- The task-aware success metric is necessary for ROSClaw tasks whose success
  condition differs from the generic `pose_reached` default.
- `pick_object` should be reported as **solved at the capability level**, and
  future cross-task transfer experiments should focus on tasks where success is
  not already saturated (e.g. `goal_pose`).
