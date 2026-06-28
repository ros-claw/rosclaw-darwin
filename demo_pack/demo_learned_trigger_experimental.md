# Demo: Learned trigger + bounded residual

**Evidence card:** `learned_trigger_bounded_residual_experimental`

**What it shows:**
- The learned trigger + bounded residual micro-policy is safe (no new failures).
- It did not rescue any seeds in paired evaluation.
- Status remains `experimental_only`.

**Run:**
```bash
darwin pair-eval \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --baseline configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --candidate configs/policies/heuristic_servo_goal_pose_v3_triggered_learned.yaml \
  --seeds 0:199 --out demo_outputs/pair_learned --mock

darwin card \
  --candidate learned_trigger_bounded_residual_experimental \
  --out demo_outputs/cards --mock
```

**Allowed claims:**
- Component is implemented and live control is safe.

**Blocked claims:**
- It improves success rate.
- It is a promoted recovery.
