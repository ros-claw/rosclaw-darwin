# Final Asset Fidelity Report

**Scope:** Separating official `dex_cube` benchmark results from procedural-cube fallback diagnostics on the ROSClaw-Darwin `goal_pose` task, and documenting why the two assets behave differently.

**Date:** 2026-06-17

## Executive summary

- **Official asset:** `dex_cube` (registered USD asset) achieves **20/20 success**
  with the `franka_ik_abs` embodiment and the abs policy.  The updated v3
  policy (`abs + ObjectGeometryAdapter + verify_object_following`) also
  succeeds on seed 0 (success_rate=1.0, progress=0.7331).
- **Procedural fallback:** When the local Docker runtime cannot resolve
  `dex_cube`, Arena silently substitutes a `procedural_cube`.  The fallback
  object is not geometrically or physically identical to `dex_cube`, so results
  on the fallback cannot be claimed as official benchmark results.
- **Asset resolution infrastructure** now detects this substitution at
  environment-load time and marks fallback runs as `leaderboard_excluded=True`
  with an explicit `asset_fidelity_diagnostic` scope.
- **Paired trace diff** (seeds 0–4) compares per-step behavior on the official
  asset vs. the fallback.  With the updated v3 policy the official asset remains
  **5/5 success** while the fallback remains **0/5**.
- **ObjectGeometryAdapter** scales grasp thresholds to the loaded object.  The
  reference tuning was updated to match the proven abs policy so the dex_cube
  keeps its 20/20 tuning while larger objects receive proportionally scaled
  values.
- **Honest conclusion:** silent asset substitution is a real benchmarking hazard.
  Official claims must use `configs/tasks/goal_pose_dex_cube_official.yaml` and
  the `dex_cube` asset; procedural-cube runs are explicitly out-of-distribution
  diagnostics.  Geometry adaptation removes threshold mismatch as a hidden
  variable but does not fix the procedural fallback's lift failure.

## Sprint 0 — Asset resolution and fallback policy

### What changed

- `rosclaw_darwin/evaluation/asset_resolution.py`:
  - `AssetResolution`, `AssetPolicy`, `BenchmarkValidity` dataclasses.
  - `resolve_asset_from_scene()` inspects scene keys and object class names.
  - `compute_benchmark_validity()` decides whether a run can claim an official benchmark.
- `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py`:
  - Inlined `_AssetResolution`, `_AssetPolicy`, `_BenchmarkValidity`.
  - `_patched_load_env()` always runs asset resolution after env load.
  - Aborts if `require_official_asset=true` and a fallback is detected.
- `rosclaw_darwin/adapters/arena.py`:
  - Forwards `asset_policy` metadata into Docker jobs.
  - Reads `asset_info` / `benchmark_validity` from container output.
  - Sets `leaderboard_excluded=True` for non-official results.

### Validation

```yaml
# configs/tasks/goal_pose_dex_cube_official.yaml
asset_policy:
  require_official_asset: true
  allow_procedural_fallback: false
  diagnostic_variant: false
```

20-seed validation:

```text
status: completed
leaderboard_excluded: False
exclusion_reason: None
asset_info: requested_object=dex_cube loaded_object=dex_cube asset_source=usd_asset official_asset=True
benchmark_validity: can_claim_official_benchmark=True validity_scope=official_arena_asset
success_rate: 20/20
```

```yaml
# configs/tasks/goal_pose_procedural_cube_ood.yaml
asset_policy:
  require_official_asset: false
  allow_procedural_fallback: true
  diagnostic_variant: true
```

Result:

```text
status: completed
leaderboard_excluded: True
exclusion_reason: loaded_object_instead_of_procedural_cube
asset_info: requested_object=procedural_cube loaded_object=object asset_fallback_used=True fallback_reason=loaded_object_instead_of_procedural_cube official_asset=False
benchmark_validity: can_claim_official_benchmark=False validity_scope=asset_fidelity_diagnostic
```

## Sprint 1 — Official result isolation

- `leaderboard_excluded=True` is applied automatically when
  `can_claim_official_benchmark` is false.
- Dashboard and reports must treat `dex_cube` official runs separately from OOD
  diagnostic runs.

## Sprint 2 — Paired trace diff

- Script: `scripts/diagnostics/run_dex_vs_procedural_paired_trace.py`
- Runs `dex_cube` official and `procedural_cube` OOD for shared seeds.
- Compares per-step traces: first GRASP step, min z/dist error, object z max.
- Output:
  - `/tmp/rosclaw_data/dex_vs_procedural_paired_trace/paired_trace_diff_report.json`
  - `/tmp/rosclaw_data/dex_vs_procedural_paired_trace/paired_trace_diff_report.csv`

**Results (2026-06-17, seeds 0–4, `heuristic_servo_goal_pose_abs.yaml`):**

| metric | dex_cube | procedural_cube | Δ |
|---|---:|---:|---:|
| success_rate | **5/5** | 0/5 | +1.0 |
| min_grasp_z_error (mean) | 0.00446 m | 0.00887 m | +0.00441 m |
| min_grasp_dist_error (mean) | 0.00527 m | 0.00903 m | +0.00376 m |
| object_z_max (mean) | **0.509 m** | 0.200 m | +0.309 m |
| object_z_final (mean) | 0.397 m | 0.047 m | +0.350 m |
| final_phase | DESCEND | DESCEND | — |

**Results with updated v3 policy (`heuristic_servo_goal_pose_v3.yaml`, seeds 0–4):**

| metric | dex_cube | procedural_cube | Δ |
|---|---:|---:|---:|
| success_rate | **5/5** | 0/5 | +1.0 |
| min_grasp_z_error (mean) | 0.00351 m | 0.00906 m | +0.00555 m |
| min_grasp_dist_error (mean) | 0.00441 m | 0.00915 m | +0.00474 m |
| object_z_max (mean) | **0.543 m** | 0.200 m | +0.343 m |
| object_z_final (mean) | 0.396 m | 0.047 m | +0.349 m |

**Interpretation:**

- The official `dex_cube` succeeds on every seed with both the abs and v3
  policies; the object is lifted to z ≈ 0.51–0.54 m.
- The procedural fallback fails on every seed; the object never leaves the
  table (z_max ≈ 0.20 m is the spawn/fall height).
- The v3 policy with geometry adaptation does not degrade official-asset
  performance and confirms that threshold scaling is not the reason the
  fallback fails.
- The trace phase field only reports `APPROACH`/`DESCEND` even for successful
  dex runs, so `grasp_step` and `final_phase` are not reliable in this
  container configuration.  Success rate and object height are the trustworthy
  signals.

## Sprint 3 — DESCEND→GRASP gate audit

- `HeuristicServoGoalPosePolicy` records gate diagnostics in the `DESCEND` phase:
  - `grasp_dist_error`
  - `grasp_z_error`
  - `condition_dist_ok`
  - `condition_z_ok`
  - `transition_allowed`
  - `transition_blocking_reason`
- `run_eval.py` aggregates:
  - `descend_exit_rate`
  - `grasp_phase_reached_rate`
  - `dominant_blocking_reason_distribution`

This lets us distinguish "policy never reached GRASP" from "policy reached GRASP but lost the object later".

## Sprint 4 — ObjectGeometryAdapter

- Module: `rosclaw_darwin/evaluation/object_geometry.py`
- Scales `grasp_dist_threshold`, `grasp_z_tolerance`, `approach_offset_z`,
  `lift_height`, `gripper_close_threshold`, `min_grasp_steps`,
  `object_following_distance_threshold`, and `align_max_delta` to the loaded
  object's width/depth/height.
- **Reference values updated to match the proven `heuristic_servo_goal_pose_abs`
  policy** (0.05 m dex_cube: grasp_dist=0.04, grasp_z=0.005, approach_z=0.10,
  lift_h=0.30, gripper_close=0.012, min_grasp=30).
- Integrated into `HeuristicServoGoalPosePolicy` and enabled in
  `configs/policies/heuristic_servo_goal_pose_v3.yaml`.
- Forwarded from task metadata through `arena.py` and captured from scene in
  `run_eval.py`.
- Unit tests: `tests/unit/test_object_geometry.py` (10 passed).

## Sprint 5 — Procedural fallback adaptation ablation

- New task config: `configs/tasks/goal_pose_procedural_cube_large_ood.yaml`
  (0.10 m cube) to test adapter scaling.
- With the updated adapter, a 0.10 m object receives:
  `grasp_dist=0.08`, `grasp_z=0.01`, `approach_z=0.15`, `lift_h=0.35`,
  `gripper_close=0.037`, `min_grasp=40`.
- Result (seed 0, v3 policy): **success_rate = 0.0**, `object_not_lifted`.
  The adapter scales correctly, but the procedural fallback still fails to lift,
  confirming the failure is not due to dex_cube-specific thresholds.

## Sprint 6 — Dashboard and report separation

- `leaderboard_excluded` and `benchmark_validity` already flow through
  `EvaluationResult` metadata.
- This report and `reports/GOAL_POSE_OBJECT_GEOMETRY_ADAPTATION_REPORT.md`
  document the separation.

## Sprint 7 — External issue refinement

- Consolidated in `reports/ARENA_ISSUE_TRACKER.md`.
- Key questions for Arena team:
  1. Why does `procedural_cube` silently load as `"object"` instead of
     `procedural_cube`?
  2. What are the exact spawn size/collision properties of the procedural cube
     used as fallback?
  3. Can the local Docker runtime be configured to register the real `dex_cube`
     USD asset so fallback does not occur?
  4. Is `franka_ik_abs` orientation control fully supported, or is the observed
     lack of yaw authority expected?

## Sprint 8 — Final report

This document is the final asset fidelity report.

## Reproduction checklist

1. Official dex_cube benchmark:

```bash
export ROSCLAW_ARENA_MODE=docker
PYTHONPATH="/code/rosclaw/rosclaw_darwin/rosclaw-darwin" \
  python scripts/diagnostics/run_goal_pose_trace.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --seeds 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19
```

2. Procedural fallback diagnostic:

```bash
PYTHONPATH="/code/rosclaw/rosclaw_darwin/rosclaw-darwin" \
  python scripts/diagnostics/run_goal_pose_trace.py \
  --task configs/tasks/goal_pose_procedural_cube_ood.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_abs.yaml
```

3. Paired trace diff:

```bash
PYTHONPATH="/code/rosclaw/rosclaw_darwin/rosclaw-darwin" \
  ROSCLAW_ARENA_MODE=docker \
  python scripts/diagnostics/run_dex_vs_procedural_paired_trace.py \
  --policy configs/policies/heuristic_servo_goal_pose_abs.yaml \
  --seeds 0 1 2 3 4 --cleanup
```

## Honest limitations

- The official 20/20 result and the paired 5-seed dex_cube success were obtained
  on the local Docker runtime.  If the Arena team's cloud runtime registers
  assets differently, reproducibility must be re-validated there.
- Geometry adaptation improves threshold appropriateness but cannot fix
  controller-level yaw authority issues or non-geometric physical differences
  (inertia, friction patches, contact offset).
- The paired trace diff used only 5 seeds and did not vary initial conditions
  (`task.mutation.seed` had no visible effect).  It is sufficient for
  qualitative asset-fidelity demonstration, not for statistical claims.
- The trace `phase` field only reported `APPROACH`/`DESCEND` in this container
  configuration, so gate-level phase diagnostics must be interpreted through
  success rate and object-height metrics.

## Files introduced or modified

- `rosclaw_darwin/evaluation/asset_resolution.py` (new)
- `rosclaw_darwin/evaluation/object_geometry.py` (new)
- `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` (modified)
- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` (modified)
- `rosclaw_darwin/adapters/arena.py` (modified)
- `configs/tasks/goal_pose_dex_cube_official.yaml` (new)
- `configs/tasks/goal_pose_procedural_cube_ood.yaml` (new)
- `configs/tasks/goal_pose_procedural_cube_large_ood.yaml` (new)
- `configs/policies/heuristic_servo_goal_pose_v3.yaml` (modified)
- `scripts/diagnostics/run_dex_vs_procedural_paired_trace.py` (new)
- `tests/unit/test_object_geometry.py` (new)
- `reports/GOAL_POSE_OBJECT_GEOMETRY_ADAPTATION_REPORT.md` (new)
- `reports/FINAL_ASSET_FIDELITY_REPORT.md` (this file)
- `reports/INDEX.md` (updated)

## Update (2026-06-17): seed randomization fixed; official dex_cube re-evaluated at 18/30

The previous 20/20 and 5/5 claims were confounded by a broken seed pipeline:
`task.mutation.seed` was not forwarded into the Arena environment builder, so
all seeds produced the same initial conditions.  After fixing the pipeline and
the phase-trace shadow-variable bug, the official `dex_cube` path was re-run
with 30 randomized seeds:

- **18/30 success (60%)** on `configs/tasks/goal_pose_dex_cube_official.yaml`
  with `heuristic_servo_goal_pose_v3.yaml`.
- Failures split into approach-collision seeds (7, 15, 28) and grasp-slip seeds
  (2, 4, 9, 10, 11, 12, 13, 24, 29).
- Procedural fallback remains a separate diagnostic; a new 10-seed paired gate
  audit with randomized seeds is in progress.

The old limitation about `phase` field reliability no longer applies; the
`phase` field now reports the full sequence.

The core conclusion remains: asset substitution (dex_cube → procedural_cube) is
a dominant failure mode that geometry adaptation alone does not resolve, but
the official-asset success claim must now be reported as **60% under true
randomization**, not 100% under fixed conditions.

## Update (2026-06-17): randomized paired gate audit

A 5-seed paired diff with `heuristic_servo_goal_pose_v3.yaml` under real seed
randomization confirms the asset-substitution effect:

- dex_cube: 3/5 success (60%), GRASP reached 5/5.
- procedural_cube: 0/5 success, GRASP reached 0/5.
- Procedural `min_grasp_dist_error` (0.009–0.049 m) and `min_grasp_z_error`
  (0.009–0.030 m) are systematically larger than dex (≈0.005–0.007 m).
- The procedural object occasionally falls through the floor (`object_z_final`
  ≈ -6232 m), indicating physics instability in the fallback asset.

This rules out "the policy just needs looser thresholds" as the sole explanation:
for seeds 1 and 3 the procedural errors are already near the adaptive gate
thresholds, yet the policy still cannot transition to GRASP, likely because the
grasp target computed from the object's reported pose does not match the actual
fallback geometry/origin.  Asset fidelity remains the root cause.

## Update (2026-06-17): FailureToHint v3 closed-loop demo

A closed-loop script inferred failure signatures from procedural OOD seeds and
injected recipe hints (`lower_grasp_height`, `longer_squeeze`, `grasp_adjust`).
The first run failed because recipe parameter names (`squeeze_steps`) did not
match policy config keys (`grasp_squeeze_steps`); the script was updated with a
parameter-name mapping and re-run.  After the fix:

- 4/5 seeds transitioned from `DESCEND` to `GRASP` and `LIFT`
  (`descend_exit_rate` 0.0 → 1.0).
- None of the seeds actually lifted the object (`object_height_max` remained
  0.2 m).
- Seed 4 stayed in `DESCEND` and the object fell through the floor.

This confirms that the procedural fallback failure is dominated by
asset-fidelity-induced geometry/gate mismatch and grasp-target instability.
Threshold/hint tuning can advance the state machine but cannot compensate for a
wrong grasp origin or physics instability.
