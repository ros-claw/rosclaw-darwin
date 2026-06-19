# Goal Pose Object Geometry Adaptation Report

**Status:** Sprint 4 implementation complete; paired trace diff in progress.  
**Report date:** 2026-06-17

## Purpose

Separate the "what is the object like" question from the policy state machine so
that grasp thresholds, lift height, and approach offsets scale to the object
that is actually loaded.  Historically the heuristic was tuned for a 0.05 m
dex_cube; when Arena silently falls back to a procedural cube (or when a
different object is requested) the fixed thresholds are either too tight or too
loose.  ObjectGeometryAdapter closes that gap.

## What was implemented

### 1. `rosclaw_darwin/evaluation/object_geometry.py`

Host-side, container-safe module with no IsaacLab imports.

- `ObjectGeometry` dataclass: width, depth, height, object_name, asset_source,
  plus aggregate properties (`extent`, `girth`, `radius`, `volume`).
- `AdaptedPolicyParams` dataclass: the subset of policy thresholds that are
  scaled by geometry.
- `ObjectGeometryAdapter.adapt(geometry)`:
  - Scales `grasp_dist_threshold` with extent (reference 0.04 m for a 0.05 m cube).
  - Scales `grasp_z_tolerance` with height (reference 0.005 m for a 0.05 m cube).
  - Sets `approach_offset_z = object_height + 0.05 m` and
    `lift_height = object_height + 0.25 m` so the reference tuning matches the
    proven `heuristic_servo_goal_pose_abs` policy.
  - Slightly relaxes `gripper_close_threshold` for thicker objects (reference
    0.012 m).
  - Increases `min_grasp_steps` for larger objects (reference 30 steps).
  - Scales `object_following_distance_threshold` and reduces `align_max_delta`
    for tall/extent objects.
  - All values are clamped to sane bounds.
- `extract_geometry_from_config(config)`: builds geometry from `size: [x,y,z]`
  or `dimensions: {width, depth, height}` blocks.
- `extract_geometry_from_scene(scene, object_name)`: inspects the IsaacLab/Arena
  scene for `spawn.size`, `spawn.scale`, or `get_bounding_box()` and returns
  geometry.  Safe fallbacks prevent a missing attribute from crashing the policy.

### 2. Policy integration

`rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`:

- `HeuristicServoGoalPosePolicyArgs` gained:
  - `use_object_geometry_adaptation: bool = False`
  - `object_geometry: dict | None = None`
- `HeuristicServoGoalPosePolicy.__init__` creates an `ObjectGeometryAdapter`
  when enabled and applies any geometry declared in the config.
- On the first `get_action` step, if no geometry was declared, the policy calls
  `extract_geometry_from_scene(...)` and applies the adapted parameters.
- Adapted parameters are logged to stderr for observability.

### 3. Adapter forwarding

`rosclaw_darwin/adapters/arena.py`:

- For heuristic policies, if task metadata contains `object_geometry`, it is
  merged into `policy_config_dict` and `use_object_geometry_adaptation` is
  defaulted to `True`.

`rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py`:

- Inlined container-side `_extract_geometry_from_scene` helper.
- In `_patched_load_env`, after asset resolution, the scene geometry is captured
  and injected into `_POLICY_CONFIG` when the policy enables adaptation but did
  not receive a declared geometry.
- The captured geometry is also written into the asset-info payload so it
  appears in run metadata.

### 4. Policy config

`configs/policies/heuristic_servo_goal_pose_v3.yaml` now enables:

```yaml
use_object_geometry_adaptation: true
```

### 5. New task config

`configs/tasks/goal_pose_procedural_cube_large_ood.yaml`:

- Explicit OOD diagnostic task with a 0.10 m procedural cube.
- Declares `object_geometry` and `physics_ablation.size: [0.10, 0.10, 0.10]` so
  the adapter can be validated against a known large object.

### 6. Unit tests

`tests/unit/test_object_geometry.py`:

- 10 tests covering default geometry, aggregates, serialization,
  default-cube adaptation, larger-object adaptation, clamping, config parsing,
  and adapted-params serialization.

Run:

```bash
PYTHONPATH="/code/rosclaw/rosclaw_darwin/rosclaw-darwin" \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest tests/unit/test_object_geometry.py -q
```

Result: **10 passed**.

## Adapter behavior examples

| Object | width/depth/height | grasp_dist | grasp_z | approach_z | lift_h | gripper_close | min_grasp |
|---|---:|---:|---:|---:|---:|---:|---:|
| dex_cube | 0.05 / 0.05 / 0.05 | 0.040 | 0.005 | 0.100 | 0.300 | 0.012 | 30 |
| large cube | 0.10 / 0.10 / 0.10 | 0.080 | 0.010 | 0.150 | 0.350 | 0.037 | 40 |
| very large cube | 1.00 / 1.00 / 1.00 | 0.080 | 0.020 | 1.050 | 1.250 | 0.040 | 120 |

(Clamped to maximum safe values for the very-large case.)

## Paired trace diff

The existing script
`scripts/diagnostics/run_dex_vs_procedural_paired_trace.py` was used to run:

- `configs/tasks/goal_pose_dex_cube_official.yaml`
- `configs/tasks/goal_pose_procedural_cube_ood.yaml`

with `configs/policies/heuristic_servo_goal_pose_v3.yaml` for seeds 0–4.

The script outputs:

- Per-seed traces under `/tmp/rosclaw_data/dex_vs_procedural_paired_trace/`.
- `paired_trace_diff_report.json` and `paired_trace_diff_report.csv` comparing
  grasp step, min z/dist error, and object z max between dex_cube and
  procedural_cube.

**Result location:** `/tmp/rosclaw_data/dex_vs_procedural_paired_trace/`

## Paired trace diff results

### With `heuristic_servo_goal_pose_abs.yaml` (baseline 20/20 policy)

Run: 2026-06-17, seeds 0–4.

| metric | dex_cube | procedural_cube | Δ |
|---|---:|---:|---:|
| success_rate | **5/5** | 0/5 | +1.0 |
| grasp_phase_reached | 0/5 | 0/5 | 0 |
| min_grasp_z_error (mean) | 0.00446 | 0.00887 | +0.00441 |
| min_grasp_dist_error (mean) | 0.00527 | 0.00903 | +0.00376 |
| object_z_max (mean) | **0.509** | 0.200 | +0.309 |
| object_z_final (mean) | 0.397 | 0.047 | +0.350 |
| final_phase | DESCEND | DESCEND | — |

### With `heuristic_servo_goal_pose_v3.yaml` (ObjectGeometryAdapter + verify_object_following)

Run: 2026-06-17, seeds 0–4.

| metric | dex_cube | procedural_cube | Δ |
|---|---:|---:|---:|
| success_rate | **5/5** | 0/5 | +1.0 |
| min_grasp_z_error (mean) | 0.00351 | 0.00906 | +0.00555 |
| min_grasp_dist_error (mean) | 0.00441 | 0.00915 | +0.00474 |
| object_z_max (mean) | **0.543** | 0.200 | +0.343 |
| object_z_final (mean) | 0.396 | 0.047 | +0.349 |

The v3 policy with geometry adaptation keeps the official `dex_cube` success
rate at **5/5**, while the large-procedural-cube OOD variant (0.10 m, declared
geometry) still fails with `object_not_lifted`.  The adapter logs confirm that
the thresholds scale correctly:

```text
[OBJECT_GEOMETRY] adapted to procedural_cube w=0.1000 d=0.1000 h=0.1000:
  grasp_dist=0.0800 grasp_z=0.0100 approach_z=0.1500 lift_h=0.3500
```

**Observations:**

1. With the proven absolute-mode orientation control and the updated geometry
   reference tuning, the official `dex_cube` succeeds on every seed.
2. The procedural fallback fails on every seed.  The object never leaves the
   table (z_max ≈ 0.20 m, which is the spawn/fall height).
3. The procedural cube reaches roughly 2× larger min z and dist errors during
   descent, but the dominant failure is not reaching/lifting — the policy
   reports only `APPROACH`/`DESCEND` phases even for successful dex runs,
   suggesting the state-machine phase trace is not capturing the post-grasp
   phases in this container configuration.  The success/object-height metrics
   are the reliable signal.
4. The identical traces across all five seeds indicate that
   `task.mutation.seed` did not vary the episode initial conditions in this
   run; however, the dex vs. procedural contrast is still clean because both
   assets see the same fixed initial pose.

### Earlier v3 run (confounded by skill-hint override and under-sized approach margin)

An initial run with `heuristic_servo_goal_pose_v3.yaml` failed on both assets.
Two root causes were fixed:

- The `skip_broken_yaw` skill hint forced `pre_grasp_orient=True`, creating a
  5-step settling pause above the object.  The object fell/slid out of reach.
  The override was removed; `pre_grasp_orient` is now controlled only by
  explicit config.
- The geometry adapter originally set `approach_offset_z = height + 0.03 m`
  and `lift_height = height + 0.20 m`, producing 0.08 m / 0.25 m for the
  dex_cube.  These values are lower than the proven `heuristic_servo_goal_pose_abs`
  tuning (0.10 m / 0.30 m) and caused the arm to descend too early and get
  stuck.  The adapter reference values were updated to match the abs policy.

## Expected outcomes

1. **dex_cube**: Should remain 5/5 success (official asset, adapter returns
   reference tuning).
2. **procedural_cube**: With geometry adaptation, the policy uses larger
   `grasp_dist_threshold` and `grasp_z_tolerance`, reducing the number of
   episodes stuck in `DESCEND` due to overly tight thresholds.
3. **Whether this converts `object_not_lifted` to success depends on the
   underlying cause**; previous work showed that matching DexCube collision
   properties alone did not fix the failure.  Geometry adaptation removes one
   more hidden variable from the diagnostic.

## Honest limitations

- Geometry adaptation cannot compensate for broken controller yaw authority
  (documented separately); it only makes the position thresholds appropriate
  for the loaded object.  With `franka_ik_abs` absolute-mode orientation control
  the yaw problem is bypassed.
- The adapter assumes a roughly box-like object.  Non-convex or highly
  asymmetric objects may need additional shape-aware tuning.
- Scene extraction relies on `spawn.size` or `get_bounding_box()`; assets that
  do not expose these attributes fall back to the declared config geometry or
  the 0.05 m default.

## Files changed

- `rosclaw_darwin/evaluation/object_geometry.py` (new)
- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py`
- `rosclaw_darwin/adapters/arena.py`
- `configs/policies/heuristic_servo_goal_pose_v3.yaml`
- `configs/tasks/goal_pose_procedural_cube_large_ood.yaml` (new)
- `tests/unit/test_object_geometry.py` (new)

## Next steps

1. Wait for paired trace diff to complete and inspect
   `paired_trace_diff_report.csv`.
2. Run the large-procedural-cube OOD task to confirm adapter scales correctly
   to a 0.10 m object.
3. Update the final asset fidelity report with geometry-adaptation evidence.
4. Refine the Arena external issue to note that silent fallback combined with
   fixed thresholds is a benchmarking hazard.

## Update (2026-06-17): mass/friction-aware adaptation and randomized dex_cube matrix

`ObjectGeometry` now carries optional `mass` and `static_friction` fields, and
`ObjectGeometryAdapter` uses them when scene extraction provides them:

- Heavy objects (`mass > 0.15 kg`): extra `min_grasp_steps` proportional to mass
  excess, and `gripper_close_threshold` tightened by 15%.
- Low-friction objects (`static_friction < 0.35`): +5 grasp steps and a 15%
  tighter close threshold.

These overrides are guarded by `is not None`, so dex_cube (no mass/friction
exposed) continues to receive the reference tuning and remains non-regressive.
Container-side fallback classes and `run_eval.py` were updated to read
`spawn.mass_props.mass` / `spawn.physics_material.static_friction` (with
`obj.data` fallbacks) so Docker runs benefit too.

A 30-seed randomized matrix on official `dex_cube` with the v3 policy produced
**18/30 successes (60%)**.  Because the matrix only varied the placement seed,
`target_yaw` stayed constant and the per-target-yaw bin table is degenerate; the
failure modes are object initial yaw / approach collision / grasp slip rather
than threshold mismatch.  This confirms that geometry adaptation is not the
bottleneck for dex_cube under random placement; the bottleneck is grasp
stability after initial contact.

New artifacts:

- `configs/policies/heuristic_servo_goal_pose_v3_adaptive.yaml` — more
  permissive base gates plus object-geometry adaptation.
- `configs/tasks/goal_pose_procedural_cube_adaptive.yaml` — procedural fallback
  diagnostic task paired with the adaptive policy.
- `scripts/diagnostics/run_failure_to_hint_procedural_loop.py` — closed-loop
  FailureToHint v3 demo that will test whether the adaptive hints improve
  procedural fallback metrics.

### Randomized paired gate audit (dex vs procedural, 5 seeds)

A 5-seed paired diff with `heuristic_servo_goal_pose_v3.yaml` under real seed
randomization shows that the procedural fallback never reaches GRASP:

| seed | dex grasp reached | procedural grasp reached | procedural min_dist_error | procedural min_z_error |
|------|-------------------|--------------------------|---------------------------|------------------------|
| 0    | yes               | no                       | 0.0319                    | 0.0205                 |
| 1    | yes               | no                       | 0.0091                    | 0.0088                 |
| 2    | yes               | no                       | 0.0490                    | 0.0271                 |
| 3    | yes               | no                       | 0.0098                    | 0.0090                 |
| 4    | yes               | no                       | 0.0322                    | 0.0300                 |

For seeds 1 and 3 the errors are close to the adaptive thresholds
(`grasp_dist_threshold=0.05`, `grasp_z_tolerance=0.01`), so the adaptive policy
may at least reach GRASP.  For seeds 0, 2, and 4 the errors are too large for
threshold tuning alone, pointing to a grasp-target computation mismatch between
the object's reported pose and its actual fallback geometry.  This is consistent
with the asset-fidelity conclusion: geometry adaptation scales thresholds, but
it cannot fix a wrong grasp target origin.

### FailureToHint v3 closed-loop demo

The procedural adaptive task was also used in a FailureToHint v3 closed-loop
script.  Base runs produced `object_not_lifted` signatures, which triggered the
`object_not_lifted_after_grasp_recipe` and generated hints
(`lower_grasp_height`, `longer_squeeze`, `grasp_adjust`) with overrides
`grasp_offset_z: 0.035` and `squeeze_steps: 25`.  The first iteration failed
because `squeeze_steps` is not a policy config key; the script was updated to map
recipe parameter names to policy keys (`grasp_squeeze_steps`).

After the mapping fix, the hinted config advanced 4/5 seeds through the DESCEND
 gate into GRASP and LIFT (`descend_exit_rate` 0.0 → 1.0), but the object still
did not lift (`object_height_max` remained 0.2 m).  Seed 4 stayed in DESCEND and
the object fell through the floor.

This validates the signature→hint→override pipeline and shows that geometry/
threshold adaptation can improve gate progress, but it cannot fix the underlying
asset-fidelity / grasp-target-origin mismatch that prevents the procedural cube
from being lifted.
