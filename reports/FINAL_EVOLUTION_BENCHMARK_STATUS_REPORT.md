# Final Evolution Benchmark Status Report

## 1. Is `lift_object` evolution evidence stable?

**Partially.**  The 50-episode single-seed run reported earlier showed auto
hints Δsuccess ≈ +0.10.  The new multi-seed validation (60 episodes per
condition) shows a positive trend:

- without_hints: 0.317
- auto_hints: 0.383
- Δsuccess = +0.067

However, the Fisher exact p-value is 0.44 and the Wilson CIs overlap heavily.
Two of nine runs returned missing metrics, which adds uncertainty.  The
evidence is **directionally stable** but not yet statistically robust.

## 2. Do auto hints still produce a positive lift?

**Yes, directionally.**  Auto hints improved success rate in the multi-seed run,
but the effect is modest and not significant at conventional levels.

## 3. What are the CI / p-value / effect size?

| comparison | Δsuccess | Fisher exact p | odds_ratio | Δprogress |
|---|---|---|---|---|
| auto vs without | +0.0666 | 0.444 | 1.33 | +0.0086 |
| manual vs without | +0.0333 | 0.699 | 1.16 | -0.0001 |

Success-rate Wilson CIs: without [0.213, 0.442], auto [0.271, 0.510].

## 4. What is `pick_object`'s success gap?

The gap was a **metric mismatch**, not a policy failure.  The task's
`success_conditions` are `[object_lifted]`, but the Arena-side generic metric
additionally required `object_to_target_distance_min < threshold`.  Once the
metric was made task-aware, all three conditions achieved **success_rate = 1.0**.

| condition | success_rate | progress | object_height_delta |
|---|---|---|---|
| without_hints | 1.0000 | 0.9561 | 0.3059 |
| manual_hints | 1.0000 | 0.9539 | 0.2991 |
| auto_hints | 1.0000 | 0.9472 | 0.3020 |

`pick_object` is therefore a **saturated sanity-check**, not a useful
success-transfer signal.

## 5. What is `goal_pose`'s grasp stability problem?

The dominant signature is ``unstable_grasp`` / ``grasped_but_not_lifted`` /
``orientation_gap``.  The fingers close but the cube slips or is pulled out
during lift / reorientation.

A grasp-stability v2 intervention was tested:

- Pre-grasp orientation based on scene object yaw.
- Capped lift vertical delta (`max_lift_delta_z = 0.08`).
- Two-stage lift-then-reorient (`REORIENT` state).
- Manual hints: `orientation_aware_grasp`, `two_stage_reorientation`,
  `lower_lift_acceleration`, `stabilize_lift`, `longer_gripper_close`.

Results (5 episodes/condition):

| condition | success_rate | progress | object_height_delta |
|---|---|---|---|
| without_hints | 0.0 | 0.4743 | -0.1636 |
| manual_hints | 0.0 | 0.4919 | -0.0801 |
| auto_hints | 0.0 | 0.4837 | -0.1258 |

Manual hints improved progress slightly and reduced how far the object dropped,
but **success is still 0**.  The bottleneck is deeper than squeeze duration or
lift speed: likely gripper-object contact geometry / friction or the relative-mode
yaw controller authority.

## 6. Does FailureSignature v2 improve auto hints?

**Not yet tested end-to-end.**  The v2 schema, tag rules, and registry are
implemented and tested.  The next step is to replace the v1 ``failure_type``
rule file with v2 signature recipes in the ablation pipeline.

## 7. Is cross-task transfer observed?

**No validated cross-task transfer.**  `lift_object` shows a preliminary
positive trend; `pick_object` is solved by the base policy so hints cannot
produce additional success transfer; `goal_pose` shows no improvement under
squeeze/stabilize hints.  No recipe is yet ``validated_transferable_skill``.

## 8. Which hints are local adaptive hints?

All current hints:

- ``stronger_lift`` + ``target_tracking`` (lift_object auto v1)
- ``precision_target_tracking`` / ``slow_final_align`` / ``hold_at_target`` (pick manual; task saturated, no additional value)
- ``longer_gripper_close`` / ``stabilize_lift`` / ``orient_adjust`` (goal_pose squeeze/stabilize, no improvement)

## 9. Which hints are skill candidates?

None have been validated across tasks.  The v2 registry marks
``orientation_gap_recipe`` as ``skill_candidate`` based on its potential
relevance to `goal_pose`, but it has not been validated.

## 10. Is there any validated transferable skill?

**No.**

## 11. Does the Dashboard clearly display evidence?

The data schema and report artifacts are ready.  Interactive charts are not yet
implemented; the Dashboard still uses tables.  See
`DASHBOARD_EVOLUTION_EVIDENCE_REPORT.md`.

## 12. Should we expand tasks or prioritize learned policy?

**Prioritize the following before expanding tasks:**

1. Revisit `goal_pose` with a stronger grasp-stability strategy (orientation-aware
   grasp pose, lower lift acceleration, two-stage lift-then-reorient).  This is now
   the only remaining task where success is not saturated and a hint could show
   real transfer.
2. Harden `lift_object` evidence with a larger, stable multi-seed run.
3. Promote any recipe that shows positive transfer on two tasks to
   ``validated_transferable_skill``.
4. Learned policy baseline remains a background effort; do not let it block
   the heuristic + hint evidence line.

---

## Overall claim status

**Can claim:**

```text
ROSClaw-Darwin has a working failure-signature-driven hint pipeline.
The Arena-side success metric is now task-aware (object_lifted vs pose_reached).
On lift_object, auto hints show a repeated positive success-rate trend,
but the effect is modest and not yet statistically robust.
On pick_object, the base servo policy achieves 100% success once the metric
matches the task definition.
Cross-task transfer is not proven; goal_pose remains unsolved.
```

**Cannot claim:**

```text
Universal cross-task skill transfer.
Validated transferable skills.
Statistically significant evolution evidence on all tasks.
```

## Files produced in this round

- `rosclaw_darwin/analysis/statistics.py`
- `rosclaw_darwin/evaluation/reproducibility.py`
- `rosclaw_darwin/evaluation/failure_signature.py`
- `rosclaw_darwin/evolution/hint_recipe.py`
- `rosclaw_darwin/evolution/manual_hint_miner.py`
- `configs/skills/failure_signature_to_hint_rules.yaml`
- `scripts/ablations/run_lift_statistical_validation.py`
- `HeuristicServoPickPolicy` in `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- Reports:
  - `REPRODUCIBILITY_AND_STATISTICS_FOUNDATION_REPORT.md`
  - `LIFT_OBJECT_STATISTICAL_VALIDATION_REPORT.md`
  - `FAILURE_SIGNATURE_V2_REPORT.md`
  - `HINT_RULES_V2_REPORT.md`
  - `PICK_OBJECT_SUCCESS_GAP_REPORT.md`
  - `GOAL_POSE_GRASP_STABILITY_REPORT.md`
  - `CROSS_TASK_TRANSFER_SUMMARY_REPORT.md`
  - `DASHBOARD_EVOLUTION_EVIDENCE_REPORT.md`
  - `LEARNED_POLICY_BASELINE_INTEGRATION_REPORT.md`
  - `FINAL_EVOLUTION_BENCHMARK_STATUS_REPORT.md`

## Tests

- Unit + integration tests: **145 passed**.
- New test files:
  - `tests/unit/test_statistics.py`
  - `tests/unit/test_reproducibility_metadata.py`
  - `tests/unit/test_failure_signature.py`
  - `tests/unit/test_failure_signature_to_hint_rules.py`
  - `tests/unit/test_manual_hint_miner.py`
  - `tests/unit/test_hint_conflict_resolution.py`
  - `tests/integration/test_failure_signature_export.py`

## Pending

All background ablations started in this round have now completed.  The next
priority is to harden `lift_object` statistical evidence and to find a stronger
grasp-stability strategy for `goal_pose`.
