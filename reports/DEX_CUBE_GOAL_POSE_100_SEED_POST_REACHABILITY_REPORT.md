# Dex-Cube Goal Pose 100-Seed Post-Reachability Report

**Date:** 2026-06-20

**Status:** Sprint 1 of v1.7 — official 100-seed validation in progress.

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
| v1.7 post-reachability official | promoted reachability            |   100 |   **?/100** | final official score |

---

## 3. Preliminary observations

- The run is currently executing (`task bmflihkqe`).
- Seeds 0–22 have all completed with `success_rate=1.0`,
  `asset_fallback_used=false`, and
  `benchmark_validity_can_claim_official_benchmark=true`.
- No approach collisions observed so far.

---

## 4. Required metrics

- `success_rate`
- Wilson 95% CI
- Bootstrap 95% CI
- `failure_distribution`
- `approach_collision_rate`
- `workspace_unreachable_rate`
- `large_yaw_slip_rate`
- `object_not_lifted_rate`
- `orientation_not_achieved_rate`
- `physics_anomaly_rate`
- `metric_parser_error_rate`
- `asset_fallback_used_count`

These will be read from
`data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/aggregate_summary.json`
once the run finishes.

---

## 5. Answers to the Sprint 1 questions

1. **Post-reachability 100-seed success rate?** *pending completion*
2. **Significantly higher than 82/100?** *pending completion*
3. **Does it reproduce 49/50?** *pending completion*
4. **Are remaining failures no longer approach collisions?** *pending completion*
5. **Can promoted reachability be written into default v3?** Already promoted; this run validates the promotion on 100 seeds.
6. **Current official benchmark final claim?** *pending completion*

---

*ROSClaw-Darwin v1.7 Sprint 1 — to be filled after the 100-seed run completes.*
