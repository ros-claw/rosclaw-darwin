# Dex-Cube Goal Pose 100-Seed Post-Reachability Report

**Date:** 2026-06-20

**Status:** Sprint 1 of v1.7 — **completed**.

**Purpose:** Establish the final official `dex_cube` success rate after the
reachability-aware approach planner has been promoted to the frozen default
policy.

---

## 1. Method

Policy: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`

Task: `configs/tasks/goal_pose_dex_cube_official.yaml`

Command:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:99 \
  --strict-official-asset \
  --serial \
  --cleanup \
  --classify-failures \
  --save-traces-on-failure \
  --out-dir data_v17/official/dex_cube_goal_pose_100_seed_post_reachability
```

Key policy settings:

- `reachability_strategy: side_pregrasp_positive_y`
- `reachability_risk_estimator: true`
- `positive_y_workspace_risk: true`
- `pre_grasp_yaw_align_v2: false`
- `enable_regrasp: false`
- `target_yaw_override: null`

This isolates the effect of reachability promotion from yaw-align and regrasp
interventions.

---

## 2. Comparison table

| Run                             | Policy                           | Seeds | Success | Notes                |
| ------------------------------- | -------------------------------- | ----: | ------: | -------------------- |
| v1.6 old official               | v3 before reachability promotion |   100 |  82/100 | baseline clean       |
| v1.6 reachability regression    | promoted reachability            |    50 |   49/50 | 0 approach collision |
| v1.7 post-reachability official | promoted reachability            |   100 |  **99/100** | final official score |

---

## 3. Results

**Artifact:** `data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/aggregate_summary.json`

- **Total seeds:** 100
- **Valid seeds:** 100
- **Successful seeds:** 99
- **Failed seeds:** 1
- **Overall success rate:** **99/100 = 99.0%**
- **Wilson 95% CI:** [94.55%, 99.82%]
- **Bootstrap 95% CI:** [97.0%, 100.0%]
- **Progress mean:** 0.783
- **Asset fallback used:** 0 runs
- **Physics anomaly rate:** 0.0
- **Metric parser error rate:** 0.0
- **Orientation achieved rate:** 1.0

### Failure distribution

| Failure type | Count |
|---|---:|
| `unknown` | 1 |

The single failure is **seed 24**, classified as `object_not_lifted` in the per-seed
metrics (`failure_counts_object_not_lifted: 1`). It is **not** an approach
collision or workspace failure.

### Key observations

- **No approach collisions:** `approach_collision_rate = 0.0` and
  `workspace_failure_rate = 0.0`. The reachability promotion eliminated the
  positive-y / positive-yaw workspace collision cluster.
- **No large-yaw slip:** `large_yaw_slip_rate = 0.0`. The official task uses
  the native Arena target yaw (π/2); in-hand orientation failure did not occur
  under the promoted reachability-only config.
- **The remaining failure is post-lift slip / object not held:** seed 24 reached
  `GRASP` and `LIFT` but the object slipped during hold, producing a negative
  `object_height_delta` (-0.179 m) and a final eef-to-object distance of 0.54 m.
- **All 100 seeds used the official `dex_cube` asset** (`asset_fallback_used=0`).

---

## 4. Conclusion

The promoted reachability-aware approach planner is **validated** on the full official
100-seed benchmark:

- **Success rate jumped from 82/100 (82%) to 99/100 (99.0%)**.
- The improvement is statistically significant: the Wilson 95% CI for the new run
  ([94.55%, 99.82%]) does not overlap with the pre-promotion CI
  ([73.3%, 88.3%]).
- The 49/50 regression is reproduced at scale: only **one failure remains** out of
  100 seeds, and it is unrelated to reachability.
- **The remaining failure (seed 24) is post-lift slip / object not held**, not an
  approach collision or workspace failure.
- The promoted config can therefore be treated as the **current official benchmark
  policy** for `goal_pose + dex_cube + franka_ik_abs`.

## 5. Answers to the Sprint 1 questions

1. **Post-reachability 100-seed success rate?** **99/100 = 99.0%**, Wilson 95% CI
   [94.55%, 99.82%], bootstrap 95% CI [97.0%, 100.0%].
2. **Significantly higher than 82/100?** **Yes.** The confidence intervals do not
   overlap and the absolute gain is +17 percentage points.
3. **Does it reproduce 49/50?** **Yes.** Scaling to 100 seeds produced one failure,
   matching the single-failure pattern observed in the 50-seed regression.
4. **Are remaining failures no longer approach collisions?** **Yes.** The single
   failure is `object_not_lifted` (post-lift slip); `approach_collision_rate=0` and
   `workspace_failure_rate=0`.
5. **Can promoted reachability be written into default v3?** Already promoted and
   now validated on 100 seeds.
6. **Current official benchmark final claim?** `goal_pose + dex_cube +
   franka_ik_abs + heuristic_servo_goal_pose_v3_reachability_promoted` achieves
   **99/100 success** on the official asset with no asset fallback and no physics
   anomalies.

---

*ROSClaw-Darwin v1.7 Sprint 1 — completed 2026-06-20.*
