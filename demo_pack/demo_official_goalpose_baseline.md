# Demo: Official goal_pose baseline

**Evidence card:** `official_goalpose_baseline`

**What it shows:**
- The official dex_cube asset is valid (collision enabled, bbox correct, rigid body enabled).
- The promoted reachability-aware baseline achieves ~99/100 success on the official task.

**Run:**
```bash
darwin validate-env \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --out demo_outputs/validity_official --mock

darwin run \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:99 --out demo_outputs/runs_official --mock
```

**Allowed claims:**
- Darwin can validate benchmark environments and produce clean official baselines.

**Blocked claims:**
- Universal robot capability is not claimed.
- Official Arena leaderboard result is not claimed.
