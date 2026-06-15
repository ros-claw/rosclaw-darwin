# Cross-Task Transfer Summary Report

## 1. Task list and conditions

| Task | Policy | Conditions | Episodes |
|---|---|---|---|
| `darwin_mvp_03_lift_object` | `heuristic_servo_lift` | without_hints, manual_hints, auto_hints | 60 per condition (20 × 3 seeds) |
| `pick_object_001` | `heuristic_servo_pick` | without_hints, manual_hints, auto_hints | 10 per condition |
| `goal_pose_001` | `heuristic_servo_goal_pose` | without_hints, manual_hints, auto_hints | 5 per condition (updated run pending) |

## 2. Results

### `lift_object`

| condition | success_rate | 95% CI | progress |
|---|---|---|---|
| without_hints | 0.3167 | [0.213, 0.442] | 0.9135 |
| manual_hints | 0.3500 | [0.242, 0.476] | 0.9133 |
| auto_hints | 0.3833 | [0.271, 0.510] | 0.9220 |

- Δsuccess(auto vs baseline) = **+0.067**, Fisher exact p = 0.44.
- Δprogress(auto vs baseline) = **+0.009**.
- Failure mode: ``target_not_reached_after_lift`` / ``final_alignment_gap``.

### `pick_object` (with new ALIGN/HOLD policy)

| condition | success_rate | progress | failure_counts |
|---|---|---|---|
| without_hints | 0.0 | 0.9578 | ``target_not_reached_after_lift``: 10 |
| manual_hints | 0.0 | 0.9394 | ``target_not_reached_after_lift``: 7 |
| auto_hints | 0.0 | 0.9321 | ``target_not_reached_after_lift``: 10 |

- Manual hints reduced failure count from 10 to 7, but success_rate stayed at 0.
- Auto hints (v1) did not help.

### `goal_pose` (squeeze/stabilize run)

| condition | success_rate | progress | failure_counts |
|---|---|---|---|
| without_hints | 0.0 | 0.4741 | ``object_not_lifted``: 5 |
| manual_hints | 0.0 | 0.4526 | ``object_not_lifted``: 5 |
| auto_hints | 0.0 | 0.4895 | ``object_not_lifted``: 5 |

- Manual squeeze/stabilize hints did **not** improve progress; auto hints were
  slightly better (+0.015) but still left all episodes in ``object_not_lifted``.
- The original manual-hint run (``target_tracking``, ``efficient_execution``,
  ``precision_placement``) showed Δprogress +0.028, but that combination was
  not reproduced here.

## 3. Transfer levels

| Task | Level | Definition | Evidence |
|---|---|---|---|
| `lift_object` | **Level 2 (preliminary)** | success_rate positive trend | auto hints Δsuccess +6.7 pp, but not statistically significant (p=0.44) |
| `pick_object` | **Level 0 / Level 1 boundary** | no success transfer; manual hints reduced failure count | failure count 10 → 7, progress slightly lower |
| `goal_pose` | **Level 0** | no progress / success transfer with squeeze/stabilize hints | manual Δprogress -0.022; auto Δprogress +0.015; all still `object_not_lifted` |

No hint recipe has yet been promoted to **validated_transferable_skill**.

## 4. Local vs. transferable hints

| Hint / Recipe | Evidence | Classification |
|---|---|---|
| ``stronger_lift`` + ``target_tracking`` (auto v1 on lift_object) | Positive trend on lift_object only | ``local_adaptive_hint`` |
| ``precision_target_tracking`` / ``slow_final_align`` / ``hold_at_target`` (pick manual) | Reduced pick failures, no success | ``local_adaptive_hint`` |
| ``longer_gripper_close`` / ``stabilize_lift`` / ``orient_adjust`` (goal_pose squeeze/stabilize) | No improvement in this run | ``local_adaptive_hint`` with negative evidence |

## 5. Failure-signature insight

The same ``target_not_reached_after_lift`` failure type has different signatures:

- ``lift_object``: mix of ``final_alignment_gap`` and ``high_progress_zero_success``.
- ``pick_object``: purely ``final_alignment_gap`` / ``lifted_but_not_aligned``.
- ``goal_pose``: ``unstable_grasp`` / ``grasped_but_not_lifted`` / ``orientation_gap``.

This confirms that v2 signature-driven rules are necessary; v1 failure-type
rules are too coarse for cross-task transfer.

## 6. Honest conclusion

Cross-task transfer is **not yet proven**.  `lift_object` shows the strongest
preliminary evidence (positive auto-hint success trend), but it is not robust
across seeds and not reproduced as success transfer on `pick_object` or
`goal_pose`.  `pick_object` and `goal_pose` each show small manual-hint
progress signals, but the dominant failure modes (final alignment and grasp
stability) are not yet solved by the current auto-hint rules.

The failure-to-hint **pipeline** itself works cross-task: Loop 1 failures are
mapped to hints and injected into Loop 2 for every task.  What is missing is a
**validated recipe** that reliably converts the mapped signature into a success
improvement on more than one task.

## 7. Next steps

1. Revisit `goal_pose` with a stronger grasp-stability strategy (orientation-aware
   grasp pose, lower lift acceleration, two-stage lift-then-reorient).
2. Tune `pick_object` alignment gain / hold duration to convert the reduced
   failure count into non-zero success.
3. Mine the manual-hint improvements on `pick_object` into candidate
   `HintRecipe`s and validate them on fresh runs.
4. Re-run `lift_object` statistical validation with ≥50 episodes per seed and
   stable metric export to harden the Level 2 claim.
5. Integrate FailureSignature v2 auto-hint generation into the ablation pipeline
   and test whether signature-driven recipes outperform v1 failure-type rules.
