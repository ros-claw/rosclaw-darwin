# Demo: Procedural fallback invalidity

**Evidence card:** `procedural_fallback_invalid_environment`

**What it shows:**
- The procedural cube fallback has disabled collision geometry and an invalid bounding box.
- Darwin blocks it as `invalid_environment` and prevents invalid benchmark results.

**Run:**
```bash
darwin validate-env \
  --task configs/tasks/goal_pose_procedural_cube_fallback.yaml \
  --out demo_outputs/validity_procedural --mock
```

**Allowed claims:**
- Darwin prevents invalid benchmark environments from polluting skill evaluation.

**Blocked claims:**
- Policy failed on procedural cube.
- Cross-object generalization failed.
