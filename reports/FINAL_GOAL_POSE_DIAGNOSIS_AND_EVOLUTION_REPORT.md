# Final Goal Pose Diagnosis and Evolution Report

This report answers the 12 questions from the v1.3 implementation outline.

## 1. Is goal_pose failure caused by gripper closure limits?

**No.** Empty close reaches ~0.00012 m. Cube-blocked close reaches ~0.024 m
with a moderate command, which is normal for a held cube.

## 2. Is gripper_pos = 0.024 normal or abnormal?

**Normal** for a cube held between the fingers.

## 3. Is the yaw action channel effective?

**No.** Rotational calibration showed zero change in eef roll/pitch/yaw for
all `action[..., 3:6]` axes.

## 4. Does the object follow eef rotation?

The object follows eef translation (mean distance ~5 mm), but it does not
follow controlled eef yaw because eef yaw does not change.

## 5. Where does failure occur: lift, hold, or reorient?

Lift-only and lift-hold succeed. Failure first appears when any yaw
requirement is added, so the boundary is **reorientation / yaw alignment**.

## 6. Do friction / cube size / mass significantly affect results?

**No clear effect.** High friction, smaller cube, and lighter cube all lift
the cube but none achieve target yaw.

## 7. Which goal_pose subtask fails first?

`goal_pose_lift_small_yaw` is the first failing subtask.

## 8. Did policy v3 improve any subtask?

**Yes — the updated v3 policy succeeds on the official `dex_cube` asset.**

A v3 intervention was implemented with the following changes:

- Added `VERIFY_OBJECT_FOLLOWING` after `LIFT` to detect slips early.
- Consumed v3 recipe parameters (`yaw_step_size`, `stabilize_steps_after_yaw`,
  `verify_object_following_steps`) and new hints (`skip_broken_yaw`,
  `verify_object_following`).
- Integrated `ObjectGeometryAdapter` so grasp thresholds, approach offset, and
  lift height scale to the loaded object.
- Updated the geometry adapter's reference tuning to match the proven
  `heuristic_servo_goal_pose_abs` policy.

Single-episode trace comparison (seed 0,
`configs/policies/heuristic_servo_goal_pose_v3.yaml`):

| metric | baseline abs | v3 (updated) |
|---|---:|---:|
| success_rate | 1.0 | **1.0** |
| progress_mean | 0.7344 | 0.7331 |
| object_height_max | 0.5095 m | 0.5427 m |
| eef_to_object_distance_min_mean | 0.0034 m | 0.0031 m |

The updated v3 policy retains the official-asset success rate while adding
geometry adaptation and object-following verification.  On the large procedural
fallback (0.10 m cube) it still fails with `object_not_lifted`, which isolates
the problem to asset fidelity rather than threshold tuning.

The historical broken-yaw v3 intervention (which held the object ~9× longer but
still scored 0 success) is documented in `reports/POLICY_V3_INTERVENTION_REPORT.md`.
It is superseded by the `franka_ik_abs` absolute-mode orientation path.

## 9. Are auto hints v3 better than v1/v2?

**Infrastructure is proven; end-to-end ablation still pending.**

The v3 hint recipes (`rotation_induced_slip_recipe`,
`yaw_not_transferred_recipe`, `blocked_gripper_normal_recipe`) are loaded in
`failure_signature_to_hint_rules.yaml`, and the evolution runner consumes them
via `FailureToHintEngine.suggest_from_signatures()` with `parameter_overrides`
flowing into `policy_config_dict`.  Unit tests pass
(`tests/unit/test_failure_to_hint.py`,
`tests/unit/test_failure_signature_to_hint_rules.py`).

A full closed-loop ablation that *starts* from failure signatures and ends with
a new success has not been run, because the current best policy already
succeeds on the official asset.  The auto-hint pipeline is now most useful for
future tasks/assets where the initial policy fails and recipe overrides can be
validated.

## 10. Is there cross-task transfer?

**No validated transferable skill.**  Grasp-stability hints show Level-2
subtask success on `goal_pose_lift_only` / `lift_hold`, but they do not solve
reorientation and have not been proven to transfer across task families.

## 11. Are there validated transferable skills?

**No.**

## 12. Next step: policy, learned policy, or Arena team?

**Priority 1: resolve the procedural-cube fallback discrepancy with the Arena team.**

With `franka_ik_abs` and the updated geometry adapter, the official `dex_cube`
asset succeeds.  The remaining open question is why the procedural fallback
(object name `"object"`, spawned as a procedural cube) fails to lift even when
thresholds, size, and collision properties are matched as closely as possible.
Likely causes include inertia, contact material, spawn height, or unobserved
USD-level physics overrides.

Recommended questions for the Arena team:

1. Why does `procedural_cube` silently load as `"object"` instead of
   `procedural_cube` in the `cube_goal_pose` environment?
2. What are the exact spawn size, mass, inertia, and contact material of the
   procedural fallback?
3. Can the local Docker runtime be configured to register the real `dex_cube`
   USD asset so fallback does not occur?
4. Is `franka_ik_abs` orientation control fully supported, or is the local
   patch (`use_relative_mode=False`) the recommended path?
5. What is the recommended gripper force / contact material for long holds?

Once asset fidelity is clarified, re-run the full subtask decomposition and
object-generalization matrix.

---

## Summary

ROSClaw-Darwin has completed a rigorous physical diagnosis of the `goal_pose`
bottleneck.  The work satisfies the v1.3 minimum acceptance standards:

- trace schema v2 separates eef yaw and object yaw;
- gripper empty/blocked calibration is complete;
- grasp success no longer relies on a single gripper_pos threshold;
- rotational action calibration is complete;
- goal_pose subtasks are decomposed and the first failing subtask is identified;
- physics ablation (high friction, smaller cube, lighter cube) is complete;
- FailureSignature v3 distinguishes rotation-induced slip / hold instability / grasp issues;
- external review package is generated.

The orientation-control blocker was resolved locally with a patched
`franka_ik_abs` embodiment.  The updated v3 policy adds
`ObjectGeometryAdapter` and `VERIFY_OBJECT_FOLLOWING` while retaining the
official-asset success rate.

The remaining blocker is **asset fidelity**: the procedural fallback used when
`dex_cube` is unavailable behaves differently and fails to lift even when the
policy thresholds are scaled to the fallback's size.  This question is now
packaged for the Arena team.


## Update (2026-06-16/17): orientation control resolved with `franka_ik_abs`, geometry adaptation validated

The controller/embodiment blocker described in section 12 was resolved locally
by creating a patched `franka_ik_abs` embodiment with `use_relative_mode=False`
and an 8-D absolute pose action space
`[pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w, gripper]`.

Key implementation details:

- All world-frame poses are converted to the robot base frame before being written into the action.
- Orientation targets are commanded as absolute quaternions and clamped per-step to limit roll/pitch coupling and grasp slip.
- `HOLD` / `RELEASE` explicitly command the current end-effector pose because a zero action vector means "move to origin" in absolute mode.
- The initial joint pose is fixed and joint randomization is disabled for reproducible resets.

Validation:

- Isolated single-seed runs of seeds 0–19: **20/20 success**, `success_rate = 1.0`, `progress_mean ≈ 0.7344`.
- Updated v3 policy (`heuristic_servo_goal_pose_v3.yaml`) with geometry
  adaptation and `VERIFY_OBJECT_FOLLOWING` also succeeds on the official
  `dex_cube` asset: **5/5** paired-trace seeds, object z_max ≈ 0.543 m.
- Paired trace diff with v3 policy: official `dex_cube` **5/5 success**,
  procedural fallback **0/5 success**, confirming asset substitution is the
  dominant failure mode.
- Large procedural-cube OOD (0.10 m, geometry adapter scaling applied) still
  fails with `object_not_lifted`, isolating the problem to asset fidelity rather
  than threshold tuning.
- A dedicated sequential multi-seed wrapper, `scripts/diagnostics/run_goal_pose_seed_sweep.py`, runs seeds one-at-a-time and optionally kills lingering Arena containers (`--cleanup`).
- `ArenaRunner._run_docker` now bind-mounts a per-run private trace directory (`_trace_dir`) into each container, eliminating the shared `episode_trace.jsonl` race.
- Concurrent multi-seed runs are still unreliable due to GPU/container resource contention, not the trace bind-mount.
- A clarification request was filed with the IsaacLab-Arena team: [isaac-sim/IsaacLab-Arena#797](https://github.com/isaac-sim/IsaacLab-Arena/issues/797).

Updated honest conclusion:

- `cube_goal_pose` is solved under clean, isolated evaluation conditions using `franka_ik_abs`.
- The solution is a local workaround (patched embodiment), not an official Arena fix.
- Geometry adaptation is validated as non-regressive; the procedural fallback
  remains an asset-fidelity blocker.

## Update (2026-06-17): v1.5 P0 infrastructure fixes and 30-seed randomized matrix

Following external expert review, two P0 infrastructure bugs were fixed before
re-running any generalization claim:

1. **Phase trace reliability.**  `HeuristicServoGoalPosePolicy.__init__`
   shadowed `_last_gate_diagnostics`; `reset()` called `super().reset()` but
   never cleared the child copy.  Stale `DESCEND` diagnostics from the previous
   episode overwrote the `phase` field in trace records of the next episode.
   `reset()` now explicitly sets `self._last_gate_diagnostics = None`.

2. **Seed randomization.**  `task.mutation.seed` was read by diagnostic scripts
   but never forwarded into the Arena environment builder.  All seeds therefore
   produced identical initial conditions.  The seed is now forwarded through
   `ArenaAdapter` → `ArenaRunner._run_docker()` → container env vars
   `ROSCLAW_ARENA_SEED` / `ROSCLAW_ARENA_PLACEMENT_SEED` → policy-level object
   pose perturbation on step 0.

A full 30-seed randomized validation matrix was run for
`heuristic_servo_goal_pose_v3.yaml` on the official `dex_cube` asset:

- **18/30 successes (60%)**
- Mean progress: 0.634
- Phase reach rates: DESCEND exit 0.90, GRASP 0.90, LIFT 0.90
- `target_yaw` was constant at ~1.57 for all seeds (placement-seed only), so
  per-target-yaw bin analysis is degenerate.
- Initial object-yaw bin success: `[-0.5, 0)` → 8/12 (66.7%), `[0, 0.5)` → 10/18
  (55.6%).

Two failure modes emerged:

1. **Approach collision** (seeds 7, 15, 28): the gripper pushed the object
   during approach; `descend_exit_rate=0`, final eef-to-object distance > 0.6 m.
2. **Grasp slip after LIFT** (9 seeds): state machine reached GRASP/LIFT, but
   `object_height_max` stayed at 0.2 m, indicating the object slipped out during
   lift.

This result is **honest but not leaderboard-clean**: it shows that the earlier
fixed-seed 20/20 claim was over-optimistic because seed randomization had been
broken.  The policy is genuinely robust to many initial poses, but not all.

Object-aware adaptation was extended to include optional `mass` and
`static_friction` fields in `ObjectGeometry`.  `ObjectGeometryAdapter` now
increases `min_grasp_steps` and tightens `gripper_close_threshold` for heavy or
low-friction objects.  Container-side fallback code and `run_eval.py` were kept
in sync.  This prepares the ground for the procedural-fallback adaptation loop,
but does not yet claim to fix it.

The next pending steps are:

- Paired gate audit on dex vs procedural cube with randomized seeds.
- Closed-loop FailureToHint v3 demo on procedural OOD seeds.
- Target-orientation seed sweep (`goal_pose_lift_small_yaw.yaml`,
  `goal_pose_lift_90_yaw.yaml`) once the environment exposes that seed.

## Update (2026-06-17, continued): procedural paired gate audit

A 5-seed paired trace diff was run with randomized seeds using
`heuristic_servo_goal_pose_v3.yaml`:

| seed | dex success | procedural success | dex grasp reached | procedural grasp reached | procedural min_dist_error | procedural min_z_error |
|------|-------------|--------------------|-------------------|--------------------------|---------------------------|------------------------|
| 0    | 1.0         | 0.0                | yes               | no                       | 0.0319                    | 0.0205                 |
| 1    | 1.0         | 0.0                | yes               | no                       | 0.0091                    | 0.0088                 |
| 2    | 0.0         | 0.0                | yes               | no                       | 0.0490                    | 0.0271                 |
| 3    | 1.0         | 0.0                | yes               | no                       | 0.0098                    | 0.0090                 |
| 4    | 0.0         | 0.0                | yes               | no                       | 0.0322                    | 0.0300                 |

Aggregate: dex 3/5 success (60%), procedural 0/5 success; procedural grasp
reached rate 0/5.

Key observations:

- The procedural cube never exits `DESCEND`; the policy stays in DESCEND for
  ~1800–2200 steps (versus 14–68 for dex).
- `min_grasp_dist_error` and `min_grasp_z_error` are consistently larger for
  procedural, indicating the gripper is not aligning with the object's actual
  grasp surface.
- For seeds 1 and 3, the errors are small (~0.009 m), close to the adaptive
  thresholds (`grasp_dist_threshold=0.05`, `grasp_z_tolerance=0.01`).  This
  suggests the adaptive policy may at least reach GRASP on those seeds.
- The procedural object sometimes falls through the floor (`object_z_final`
  ~ -6232 m), confirming asset-fidelity/physics instability in the fallback.

Conclusion: the procedural failure is a **geometry/gate mismatch plus physics
instability**, not simply a threshold scaling problem.  Mass/friction-aware
adaptation and wider adaptive gates are the next intervention; full success is
not expected.

Next: run the FailureToHint v3 closed-loop demo to see if adaptive hints
improve `descend_exit_rate` or `object_lifted_rate` on procedural seeds.

## Update (2026-06-17, continued): FailureToHint v3 closed-loop demo on procedural OOD

A 5-seed closed-loop script (`run_failure_to_hint_procedural_loop.py`) ran the
base v3 policy on the procedural adaptive task, inferred `FailureSignature` v3
tags from each trace, queried `FailureToHintEngine` for hints, and re-ran the
same seed with the hinted config.

Base result for all 5 seeds: `success_rate=0.0`, `descend_exit_rate=0.0`,
`object_height_max=0.2` — identical to the OOD paired audit.

Generated hints (from `object_not_lifted_after_grasp_recipe`):

- `lower_grasp_height`
- `longer_squeeze`
- `grasp_adjust`

with parameter overrides `grasp_offset_z: 0.035` and `squeeze_steps: 25`.

First iteration: all hinted runs returned `status: "failed"` with no metrics.
Root cause: the recipe uses generic parameter names (`squeeze_steps`) that do
not match the policy config keys (`grasp_squeeze_steps`).  The hinted config
therefore contained an unknown field and the policy runner errored out.  The
script was updated with a `_RECIPE_PARAM_MAP` to translate generic recipe names
into policy-specific keys.

After the mapping fix the demo was re-run on seeds 0–4.  Results:

| seed | base descend_exit | hinted descend_exit | base grasp | hinted grasp | base lift | hinted lift | object lifted? |
|------|-------------------|---------------------|------------|--------------|-----------|-------------|----------------|
| 0    | 0.0               | 1.0                 | 0.0        | 1.0          | 0.0       | 1.0         | no             |
| 1    | 0.0               | 1.0                 | 0.0        | 1.0          | 0.0       | 1.0         | no             |
| 2    | 0.0               | 1.0                 | 0.0        | 1.0          | 0.0       | 1.0         | no             |
| 3    | 0.0               | 1.0                 | 0.0        | 1.0          | 0.0       | 1.0         | no             |
| 4    | 0.0               | 0.0                 | 0.0        | 0.0          | 0.0       | 0.0         | no             |

Interpretation:

- The FailureToHint v3 pipeline **works end-to-end**: signature extraction →
  recipe selection → hint/override injection → re-run.
- For 4/5 seeds, the generated hints (`lower_grasp_height`, `longer_squeeze`,
  `grasp_adjust`) allowed the policy to **transition through DESCEND and reach
  GRASP/LIFT** (`descend_exit_rate` 0.0 → 1.0).
- However, the object still did not lift (`object_height_max` stayed at 0.2 m,
  `object_height_delta` ≈ -0.178 m).  The gripper closes around the object but
  the object slips, exactly the same grasp-stability signature seen in the
  randomized dex_cube failures.
- Seed 4 remained stuck in DESCEND and the object fell through the floor
  (`object_height_delta` ≈ -4081 m), confirming that for some initial poses the
  asset-fidelity/physics instability is too severe for threshold tuning.

Honest conclusion: the FailureToHint v3 infrastructure is functional and can
produce measurable phase-progress improvements on procedural OOD, but full
success requires fixing the underlying grasp-stability / asset-fidelity issue,
not just applying recipe overrides.

Updated honest conclusion for v1.5:

- Official `dex_cube` under true randomization: **48% success** (24/50, clean
  sequential 50-seed run).  The earlier 30-seed 60% was an optimistic estimate.
- Procedural fallback: **0% success**, but adaptive hints improved
  `descend_exit_rate` on 4/5 seeds.
- The dominant blocker is **grasp stability after contact** on dex_cube and
  **geometry/gate mismatch + physics instability** on procedural fallback.
- Cross-target-yaw diagnostic shows orientation achievement is flat (~40%)
  across yaws; the bottleneck is grasp slip, not yaw authority.
- Strong-grasp ablation (longer squeeze / tighter close threshold) fixed 0/9
  slip seeds.
- `franka_ik_abs` remains a local workaround; target-orientation generalization
  is bounded by grasp stability.
- Generalisation to other objects/target orientations and robust concurrent evaluation remain open.

---

## Update (2026-06-18): orientation generalization probe in progress

The previous 30-seed matrix varied placement seed but left `target_yaw` fixed
at `~1.5708` rad.  To address the "target-orientation generalization is still
unvalidated" limitation, I added a `target_yaw_override` parameter to
`HeuristicServoGoalPosePolicy` and started a 5×10 cross-target-yaw diagnostic
matrix (target yaws 0.0, 0.52, 0.79, 1.05, 1.57 rad; seeds 0–9).

Because the Arena `cube_goal_pose` environment does not expose a variable
target yaw, this override only changes the policy's commanded target; the
environment's own success criterion is still evaluated against its original
`pi/2` target.  The diagnostic therefore focuses on a custom
`orientation_achieved` metric: while the object is lifted (`object_z > 0.25` m),
does its yaw come within 0.5 rad of the override target?

A 50-seed extension of the official `dex_cube` placement-randomization matrix was
started to tighten the success-rate confidence interval.  The first attempt was
contaminated by concurrent GPU/container contention because the target-yaw
matrix was launched before the dex_cube matrix finished; most seeds returned
`status: failed` and the run is discarded.  Both scripts now have a `--cleanup`
flag, and the matrices are being re-run strictly sequentially.

The corrected sequential 50-seed run finished with **24/50 successes (48%)** and
**all 50 seeds returned usable metrics**.  This is a more honest estimate than
the 30-seed run's 60%; the expanded seed range includes harder initial poses.
Failure modes are unchanged: approach collision on some seeds and grasp slip
after LIFT on the majority.

The target-yaw matrix (5 yaws × 10 seeds) finished next.  The key result is
that `lifted_rate` and `orientation_achieved_rate` are **essentially flat across
all target yaws** (0.60 and 0.40 respectively).  This means the absolute-mode
orientation controller can command different yaws, but the object slips before
the alignment can be verified.  The cross-yaw bottleneck is therefore **grasp
stability after contact**, not yaw authority.

A candidate next intervention for the dominant grasp-slip failure mode was
`configs/policies/heuristic_servo_goal_pose_v3_strong_grasp.yaml`, which uses a
longer close/squeeze phase (`min_grasp_steps=45`, `grasp_squeeze_steps=25`), a
tighter `gripper_close_threshold=0.010`, and a stricter object-following check
(`verify_object_following_steps=10`).  It was evaluated on the 9 slip seeds from
the 30-seed randomized matrix.

Result: **0/9 seeds lifted the object**.  Every run reached GRASP/LIFT, but
`object_height_max` stayed at 0.2 m and `object_height_delta` was approximately
-0.179 m.  Tuning close threshold and squeeze duration within the current
heuristic framework did not prevent slip.  The root cause is therefore unlikely
to be threshold tuning alone; it may involve contact physics, gripper force
limits, object inertia, or the way the fingers close around the cube.

The decomposed subtasks were also swept (10 seeds each):

| task | success rate | note |
|---|---|---|
| `goal_pose_lift_only` | 6/10 | Still fails on grasp slip even without orientation requirement. |
| `goal_pose_lift_hold` | 5/10 | Similar failure mode. |

Updated honest conclusion for v1.5:

- Official `dex_cube` under true randomization: **48% success** (24/50, clean
  sequential run); the earlier 30-seed 60% was an optimistic estimate.
- Cross-target-yaw diagnostic: orientation achievement is flat at ~40% across
  target yaws; the cross-yaw bottleneck is grasp stability, not yaw authority.
- Strong-grasp ablation: **0/9 slip seeds fixed** by longer squeeze / tighter
  close threshold.
- Subtask decomposition: even `goal_pose_lift_only` is only 6/10 under
  randomized placement.
- Procedural fallback remains 0% success; adaptive hints improved gate progress
  but did not lift the object.
- The dominant blocker on official `dex_cube` is **grasp stability after
  contact**.
- `franka_ik_abs` remains a local workaround.

## Update (2026-06-18): GRASP pose-hold bug fix changes the diagnosis

Trace inspection of the strong-grasp seed 2 run showed the end-effector
continuing to descend during `GRASP` while the gripper closed.  The `GRASP`
state only wrote the gripper command and left the arm action as zeros; in
`franka_ik_abs` absolute mode a zero pose command drifts toward the origin,
making the fingers close beside or under the cube.  Once the arm lifted, the
cube stayed on the table, producing the "grasp slip after LIFT" signature.

The fix is to hold the current end-effector pose while closing in absolute mode,
mirroring the existing `HOLD` / `RELEASE` behaviour.

Re-running the 9 slip seeds from the 30-seed matrix after the fix:

| policy | success / 9 | note |
|---|---|---|
| `heuristic_servo_goal_pose_v3.yaml` (base) | **8/9** | only seed 24 still fails |
| `heuristic_servo_goal_pose_v3_strong_grasp.yaml` | **8/9** | only seed 2 anomalous |

This is a large improvement over the pre-fix **0/9**.  The dominant failure
mode on the official `dex_cube` is therefore **not** generic grasp stability or
contact physics, but a **missing pose-hold command during GRASP** for absolute
pose controllers.  The earlier strong-grasp ablation and subtask sweeps were
misdiagnosed because the same root cause affected all seeds that happened to
enter GRASP with a small downward drift.  The full 50-seed randomized matrix
with the fix finished with **44/50 successes (88%)**, up from 24/50 (48%) before
the fix.  The 6 remaining failures are approach collisions (seeds 7, 15, 28, 37,
48) and one seed (24) with systematically larger grasp alignment error.

Updated honest conclusion for v1.5:

- The official `dex_cube` path now achieves **88% success** on a clean 50-seed
  randomized placement matrix.  The earlier 48% estimate was low because the
  missing GRASP pose-hold command caused many seeds to fail with a "slip"
  signature.
- The remaining 12% failure rate is dominated by **approach collisions** on a
  small set of initial poses (object yaws around +0.10 to +0.25 rad and one
  negative-yaw seed with high grasp error).  These are not the same as the
  earlier "grasp slip" failures.
- `franka_ik_abs` remains a local workaround, and the fix is specific to
  absolute-mode controllers.
- Procedural fallback is unchanged; its failure is still dominated by
  asset-fidelity issues rather than threshold tuning.
- Cross-target-yaw generalization still needs to be re-evaluated with the fixed
  policy; the earlier 5×10 matrix was run before the fix.

## Update (2026-06-18): post-fix target-yaw matrix redefines the orientation bottleneck

The target-yaw 5×10 matrix was re-run with the GRASP pose-hold fix.  Results:

| target_yaw (rad) | lifted_rate | orientation_achieved_rate | env_success_rate |
|---|---:|---:|---:|
| 0.0000 | 0.90 | 0.90 | 0.90 |
| 0.5236 | 0.90 | 0.20 | 0.90 |
| 0.7854 | 0.90 | 0.20 | 0.90 |
| 1.0472 | 0.80 | 0.20 | 0.80 |
| 1.5708 | 0.30 | 0.10 | 0.30 |

- Small reorientations (`target_yaw ≈ 0`) are now robust: lift and orientation
  are achieved on 9/10 seeds.
- As the commanded yaw increases, the object is still lifted in most cases, but
  it rotates relative to the gripper during REORIENT/ALIGN and ends up far from
  the target yaw.  The absolute-mode controller reaches the commanded gripper
  yaw (trace `desired_eef_yaw` matches the override), so the limit is not yaw
  authority.
- At `target_yaw = π/2` the override path fails on 7/10 seeds, even though the
  default-environment π/2 target in the placement matrix achieved 88% success.
  The likely reason is that the override builds a pure world-yaw quaternion,
  whereas the native Arena command may have a different roll/pitch composition;
  after base-frame conversion the override can demand a gripper attitude that
  is hard to hold without in-gripper slip.

Approach-collision ablations on the five remaining 50-seed failures showed that
none of the obvious threshold/orientation fixes reliably solve the positive-y
workspace dead-end: `approach_offset_z=0.25` (0/5), `pre_grasp_orient=true`
(0/5), and `align_yaw_during_approach` with `approach_yaw_offset=π` (0/5 and
regressed previously successful seeds).  A frame-mismatched `approach_yaw_offset=π/2`
variant reached GRASP/LIFT on 3/5 seeds but broke the gripper-object yaw
relationship needed for final alignment.  The most likely root cause is a
kinematic/workspace boundary in the default `franka_ik_abs` reset configuration
for objects on the positive-y side of the table, not a policy-parameter mismatch.

A 50-seed matrix with `target_yaw_override=0.0` was run to isolate the workspace
limit from the π/2 reorientation effect.  Result: **45/50 successes (90%)**,
lifted_rate 0.90, orientation_achieved_rate 0.90.  The only failures are the
same 5 approach-collision seeds (7, 15, 28, 37, 48).  Seed 24, which failed in
the default π/2 matrix, succeeds when no large reorientation is required.  This
confirms that the default matrix's 6th failure is caused by the π/2
reorientation, while the 5 approach collisions are an independent workspace
limit.

Updated honest conclusion for v1.5:

- Official `dex_cube` randomized placement with the native π/2 target: **88%
  success** (44/50).  This is the honest ceiling for the current
  `franka_ik_abs` + v3 setup.
- With `target_yaw_override=0.0` the ceiling rises to **90%** (45/50); the
  remaining 10% is purely the positive-y workspace boundary.
- Seed 24's failure under the default target is due to **π/2 reorientation slip**,
  not approach collision.
- Cross-orientation generalization: **small reorientations are robust; large
  reorientations are limited by in-gripper rotation**, not by the controller's
  ability to command yaw.
- The `target_yaw_override` diagnostic probe should not be treated as an
  official cross-yaw benchmark; a true benchmark needs Arena-side support for
  `target_yaw` as a task/environment argument.
- `franka_ik_abs` remains a local workaround; procedural fallback remains an
  asset-fidelity blocker.

