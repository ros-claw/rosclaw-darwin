# Draft: Arena issue — procedural cube asset-fidelity mismatch

Use this draft to create an issue in `isaac-sim/IsaacLab-Arena`.

Suggested title:
```
[ROSClaw-Darwin v1.6] Procedural cube fallback vs. dex_cube asset-fidelity mismatch blocks GoalPose OOD generalization
```

Suggested labels: `question`, `ood-generalization`, `goal_pose`

---

## Body

We are hitting a hard blocker when extending our `cube_goal_pose` policy (`franka_ik_abs` embodiment, absolute-quaternion targets) from the official `dex_cube` asset to the procedural cube fallback. We would appreciate clarification on whether this is expected behavior and how to get a deterministic, physically-equivalent OOD object variant.

### Evidence

**Official `dex_cube` works.**
- 100-seed clean benchmark: **82/100 success** (Wilson 95% CI [73.3%, 88.3%]).
- 50-seed regression with reachability-aware approach planner: **49/50 success**, 0 approach collisions.
- The official task config resolves `loaded_object=dex_cube` and is marked `official_asset=True`.

**Procedural cube fallback fails before `DESCEND` exits.**
We ran a cross-object matrix (3 variants × 2 conditions × 5 seeds = 30 runs):

| object | condition | completed | lifted | env_success | mean `object_height_delta` | `descend_exit_rate` |
|---|---|---:|---:|---:|---:|---:|
| procedural_cube_ood | baseline_v3 | 1.0 | 0.0 | 0.0 | -2496.85 | 0.0 |
| procedural_cube_dex_size | baseline_v3 | 1.0 | 0.0 | 0.0 | -2496.85 | 0.0 |
| procedural_cube_large | baseline_v3 | 1.0 | 0.0 | 0.0 | -2496.85 | 0.0 |
| procedural_cube_ood | object_geometry_adapter_structural | 1.0 | 0.0 | 0.0 | -2496.85 | 0.0 |
| procedural_cube_dex_size | object_geometry_adapter_structural | 1.0 | 0.0 | 0.0 | -2496.85 | 0.0 |
| procedural_cube_large | object_geometry_adapter_structural | 1.0 | 0.0 | 0.0 | -2496.85 | 0.0 |

- `lifted_rate = 0.0` and `env_success_rate = 0.0` for **every cell**.
- `object_height_delta ≈ -2496 m` indicates the object sometimes falls through the floor.
- `descend_exit_rate = 0.0` means the failure happens **before the policy even enters `GRASP`**.
- Adding structural hints (`enable_regrasp`, `CONTACT_VERIFY`, `LIFT_VERIFY`) does not help because those phases are downstream of `DESCEND`.

### What we have already checked

1. **Asset resolution** detects the substitution: the requested procedural cube loads with scene key `"object"`, triggering `fallback_reason=loaded_object_instead_of_procedural_cube`.
2. **ObjectGeometryAdapter** scales grasp tolerances / approach offsets / lift height to the loaded object geometry. It does not regress official `dex_cube` but also does not enable procedural lift.
3. **Contact-proxy diagnosis** is empty because `DESCEND` never exits, so there is no grasp phase to diagnose.
4. **Size is not the root cause:** `dex_size` (same 0.05 m as `dex_cube`), `large`, and `ood` variants all fail identically.

### Questions for the Arena team

1. Is the procedural cube fallback intended to be physically equivalent to `dex_cube`? If not, what is the recommended way to register a deterministic OOD cube variant for controlled generalization experiments?
2. What are the official `dex_cube` size, mass, inertia, and friction parameters? We want to create a procedural variant that matches them exactly.
3. Why does the procedural cube spawn with scene key `"object"` instead of `"procedural_cube"`? Can the key be made deterministic?
4. Why does the object sometimes fall through the floor (`object_height_delta ≈ -2496 m`) after the policy run completes / resets?
5. Is the initial object pose / table height different between `dex_cube` and the procedural fallback? The policy descends to the same absolute z, so a small spawn-height mismatch would explain the `DESCEND` gate failure.
6. Is there an official working baseline for `cube_goal_pose` with a non-`dex_cube` object (e.g. a procedural variant)?
7. If we want to contribute a proper procedural-cube asset to IsaacLab-Arena, what is the preferred asset registration path?

### Artifacts

- Aggregate JSON: `data_v16/ablations/cross_object_matrix_v16/aggregate_summary.json`
- Cross-object/cross-yaw report: `reports/CROSS_OBJECT_CROSS_YAW_GENERALIZATION_REPORT.md`
- Procedural OOD diagnosis: `reports/PROCEDURAL_CONTACT_DIAGNOSIS_REPORT.md`
- Procedural OOD adaptive recovery: `reports/PROCEDURAL_OOD_ADAPTIVE_RECOVERY_REPORT.md`
- Consolidated issue tracker: `reports/ARENA_ISSUE_TRACKER.md`

---
*ROSClaw-Darwin v1.6 finalization, 2026-06-19*
