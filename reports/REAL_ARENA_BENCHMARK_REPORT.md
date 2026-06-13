# Real Arena Benchmark Report

**Report:** ROSClaw-Darwin Darwin-Arena-5 Real Benchmark  
**Date:** 2026-06-13  
**Metric scope:** `arena_real`  
**Claim level:** `execution` (real Arena rollouts completed; no positive success rate yet)  

## 1. Task List

| # | Task ID | Arena Env | Source | Execution |
|---|---|---|---|---|
| 1 | `darwin_mvp_03_lift_object` | `lift_object` | native | arena docker |
| 2 | `darwin_kitchen_pick_and_place_cube` | `kitchen_pick_and_place` | native | arena docker |
| 3 | `darwin_mvp_21_put_object_in_microwave_and_close_door` | `franka_put_and_close_door` | native | arena docker |
| 4 | `lw_snacksorting` | `tabletop_sort_cubes` | LW-BenchHub import | arena docker |
| 5 | `darwin_mvp_03_lift_object_mut_000` | `lift_object` | mutated variant | arena docker |

## 2. Policy Matrix

| Policy | Config Path | Purpose |
|---|---|---|
| `zero_action` | `configs/policies/zero_action.yaml` | Baseline (noop) |
| `heuristic_lift` | `configs/policies/heuristic_lift.yaml` | Non-zero heuristic without hints |
| `heuristic_lift_with_manual_hints` | `configs/policies/heuristic_lift_with_manual_hints.yaml` | Heuristic with manual skill hints |

## 3. Commands

```bash
export ROSCLAW_ARENA_MODE=docker

darwin suite run --suite configs/suites/darwin_arena_5.yaml \
  --adapter arena --policy configs/policies/zero_action.yaml \
  --loops 1 --episodes 3 --out /tmp/arena_5_zero

darwin suite run --suite configs/suites/darwin_arena_5.yaml \
  --adapter arena --policy configs/policies/heuristic_lift.yaml \
  --loops 1 --episodes 3 --out /tmp/arena_5_heuristic

darwin suite run --suite configs/suites/darwin_arena_5.yaml \
  --adapter arena --policy configs/policies/heuristic_lift_with_manual_hints.yaml \
  --loops 1 --episodes 3 --out /tmp/arena_5_hints
```

## 4. Per-Task Per-Policy Results

| Task | zero_action SR | heuristic_lift SR | heuristic + hints SR | Notes |
|---|---|---|---|---|
| `darwin_mvp_03_lift_object` | 0.0 | 0.0 | 0.0 | All runs completed; policy did not lift |
| `darwin_kitchen_pick_and_place_cube` | 0.0 | 0.0 | 0.0 | Completed; no success |
| `darwin_mvp_21_put_object_in_microwave_and_close_door` | 0.0 | 0.0 | 0.0 | Completed; no success |
| `lw_snacksorting` | 0.0 | 0.0 | 0.0 | Completed; no success |
| `darwin_mvp_03_lift_object_mut_000` | 0.0 | 0.0 | 0.0 | Completed; no success |

**Summary:** All 15 real Arena Docker rollouts (5 tasks × 3 policies) completed without execution errors. Every `success_rate` is `0.0`, which is a policy-capability result, not an infrastructure result.

## 5. Failure Map

The current Arena container output does not yet expose a detailed `failure_type` taxonomy. `failure_types` in returned `EvaluationResult` is empty for all runs. The most likely failure modes observed from stderr/stdout are:

- `object_not_lifted` — end-effector did not grasp and lift the object.
- `target_not_reached` — object not placed at destination.
- `policy_noop` / `timeout` — zero_action produces no useful motion.

Next step: extend the container-side eval runner to emit per-episode failure labels and progress signals.

## 6. Progress / Auxiliary Metrics

Currently available metrics from the container are limited to:

- `num_steps` (200 for heuristic, episode-based for zero_action)
- `num_episodes`
- `success_rate`

Per-task progress signals (object height delta, distance to goal, door angle, etc.) are not yet returned. This is a known gap and is scheduled for the next iteration.

## 7. Artifact Paths

| Policy | Summary path |
|---|---|
| zero_action | `/tmp/arena_5_zero` |
| heuristic_lift | `/tmp/arena_5_heuristic` |
| heuristic + manual hints | `/tmp/arena_5_hints` |

Individual run stderr/stdout logs are inside the Docker container's `/tmp/rosclaw_data/runs/` and are not automatically copied back to the host in the current `suite run` path.

## 8. Honest Conclusion

- ✅ **Infrastructure is real:** ROSClaw-Darwin can launch 5 distinct Arena Docker tasks with automatic environment matching and run 3 different policies end-to-end.
- ❌ **Policy capability is not yet demonstrated:** No policy achieved a non-zero `success_rate` on any task.
- ❌ **Skill transfer cannot be claimed:** Because baseline success is 0, there is no measurable `skill_transfer_gain`.

This benchmark validates the **execution and evaluation pipeline**, not the policy. The next engineering priority is to either:

1. Improve the heuristic policy to produce non-zero progress/success, or
2. Integrate a scripted/replay/learned policy that can interact reliably with Arena objects.

Only after non-zero baseline progress is observed can `auto_skill_hints` be meaningfully ablated.

## 9. Dashboard / Report Metadata

```json
{
  "metric_scope": "arena_real",
  "can_claim_capability": true,
  "claim_level": "execution"
}
```
