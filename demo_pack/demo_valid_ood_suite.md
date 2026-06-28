# Demo: Valid OOD suite

**What it shows:**
- A valid OOD cube (not the procedural fallback) can be audited and used for OOD diagnostics.
- The ObjectGeometryAdapter adapts policy parameters to the valid OOD object.

**Run:**
```bash
darwin validate-env \
  --task configs/tasks/goal_pose_valid_ood_cube.yaml \
  --out demo_outputs/validity_ood --mock

darwin run \
  --task configs/tasks/goal_pose_valid_ood_cube.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:4 --out demo_outputs/runs_valid_ood --mock
```

**Allowed claims:**
- Darwin can validate a valid OOD object and run a baseline on it.

**Blocked claims:**
- Cross-object transferable skill is not claimed.
- Procedural OOD success is not claimed.
