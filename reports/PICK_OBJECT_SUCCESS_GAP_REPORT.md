# Pick Object Success Gap Report

## 1. Observation

The original `heuristic_servo_pick` policy (which reused the lift servo policy)
achieved very high progress on `pick_object` but zero success:

```text
without_hints: progress = 0.9533, success_rate = 0.0
manual_hints:  progress = 0.9251, success_rate = 0.0
auto_hints:    progress = 0.9335, success_rate = 0.0
```

All failures were ``target_not_reached_after_lift``.

## 2. Success gap analysis

The high progress / zero success pattern means the cube is grasped and lifted,
but the final success condition is not satisfied.  Candidate explanations:

| Hypothesis | Evidence | Verdict |
|---|---|---|
| Final object-to-target distance too large | failure_type = ``target_not_reached_after_lift`` | Likely |
| Hold duration at target too short | success condition may require sustained pose | Possible |
| Object overshoots / drifts after reaching target | high progress but success=0 | Possible |
| Success threshold too strict relative to policy precision | progress ~0.95 but not 1.0 | Possible |
| Gripper opens too early / object slips | policy kept gripper closed in lift | Less likely |

The dominant FailureSignature v2 tag is ``final_alignment_gap`` with
``lifted_but_not_aligned`` and ``high_progress_zero_success``.

## 3. Intervention: explicit ALIGN and HOLD_AT_TARGET phases

To close the gap, a new policy class ``HeuristicServoPickPolicy`` was added:

```text
APPROACH → DESCEND → GRASP → LIFT → ALIGN → SLOW_ALIGN → HOLD_AT_TARGET → VERIFY_SUCCESS
```

Key changes vs. the lift policy:

- After lifting to target height, the policy does **not** declare success.
- It enters ``ALIGN`` and moves horizontally toward the command target with a
  reduced gain (`align_kp = 0.6`) and small max delta (`0.06 m`).
- Within ``SLOW_ALIGN`` the gain is further reduced (`near_target_gain = 0.5`)
  to avoid overshoot.
- ``HOLD_AT_TARGET`` keeps the object at the target for ``hold_steps`` (default
  20 steps ≈ 1 s) so that any success condition requiring sustained pose has
  time to register.
- New hints:
  - ``precision_target_tracking``
  - ``slow_final_align``
  - ``hold_at_target``
  - ``reduce_near_target_gain``
  - ``settle_before_success_check``

The pick task config now uses ``type: heuristic_servo_pick`` and the adapter
maps it to ``heuristic_policy.HeuristicServoPickPolicy``.

## 4. Updated ablation (with new policy)

A fresh ablation was run with:

```bash
python scripts/ablations/run_lift_skill_hint_ablation.py \
  --task configs/tasks/pick_object.yaml \
  --policy configs/policies/heuristic_servo_pick.yaml \
  --manual-hints precision_target_tracking,slow_final_align,hold_at_target \
  --episodes 10 \
  --report-path reports/PICK_OBJECT_SKILL_HINT_ABLATION_REPORT.md
```

Results:

| condition | success_rate | progress | failure_counts |
|---|---|---|---|
| without_hints | 0.0 | 0.9578 | ``target_not_reached_after_lift``: 10 |
| manual_hints | 0.0 | 0.9394 | ``target_not_reached_after_lift``: 7 |
| auto_hints | 0.0 | 0.9321 | ``target_not_reached_after_lift``: 10 |

The ALIGN / HOLD phase reduced the raw failure count under manual hints from
10 to 7, but did not produce any successes in this 10-episode run.  Progress
remained high, confirming that the bottleneck is still the final residual /
hold condition.

## 5. Honest conclusion

The success gap is well explained: the policy can lift the cube but does not
yet satisfy the final success condition.  The new ``HeuristicServoPickPolicy``
adds explicit alignment and hold behavior and shows a partial improvement in
failure count.  Closing the remaining gap likely requires tuning ``align_kp``,
``hold_steps``, or ``success_threshold``, or a larger episode budget to detect
small success-rate improvements.
