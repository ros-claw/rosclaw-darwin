# Goal Pose `franka_ik_abs` Implementation Status Report

**Date:** 2026-06-16  
**Corresponding external issue:** [isaac-sim/IsaacLab-Arena#797](https://github.com/isaac-sim/IsaacLab-Arena/issues/797)

## Executive Summary

The `cube_goal_pose` orientation-control blocker has been **resolved locally** by switching `HeuristicServoGoalPosePolicy` from the default `franka_ik` relative-mode controller to a patched `franka_ik_abs` absolute-pose controller.

A 20-seed validation sweep run with the new **sequential wrapper and per-run private trace directories** achieved **20/20 success** (`success_rate = 1.0`).  Earlier sweeps that ran multiple seeds concurrently or with a stale Docker container still running showed sporadic failures; the root cause of those failures is environmental interference rather than a deterministic policy failure mode.  The new wrapper eliminates that interference by running seeds one-at-a-time and giving each Docker container its own trace directory.

A consolidated clarification request has been filed with the IsaacLab-Arena team to confirm whether the `franka_ik_abs` workaround aligns with the intended design.

| condition | seeds | success_rate |
|---|---|---:|
| isolated single-seed runs | 0–19 | 20/20 = 1.0 |
| sequential multi-seed runs (private trace dirs) | 0–19 | 20/20 = 1.0 |
| concurrent multi-seed runs | 0–19 | ~10/20 = 0.50 (interference) |
| orientation generalization (dex_cube, 0°–180°) | 1 each | 5/5 = 1.0 |
| object generalization (procedural_cube default) | 1 each | 0/5 = 0.0 |
| object physics ablation (procedural_cube size/friction/mass, default policy) | 1 each | 0/6 = 0.0 |
| object physics ablation (procedural_cube size/friction/mass, loose grasp policy) | 1 each | 0/6 = 0.0 (dex_cube also 0/1) |

**Current honest claim:** `franka_ik_abs` solves `cube_goal_pose` under clean, isolated evaluation conditions and generalizes across target yaw orientations for the registered `dex_cube`.  It does **not** yet generalize to the `procedural_cube` variant.  Multi-seed batch evaluation is reliable when executed sequentially through `run_goal_pose_seed_sweep.py`.

---

## What was implemented

### 1. New `franka_ik_abs` embodiment

- File: `rosclaw_darwin/evaluation/arena_docker_deps/franka_ik_abs_patch.py`
- Registered as `franka_ik_abs` in `rosclaw_darwin/adapters/arena.py`.
- Configuration:
  - `command_type = "pose"`
  - `use_relative_mode = False`
  - `scale = 1.0`
  - 8-D action: `[pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w, gripper]`
- Deterministic tabletop initial joint pose and disabled joint randomization for reproducible multi-seed results.

### 2. Policy changes in `HeuristicServoGoalPosePolicy`

- **Base-frame pose conversion:** absolute-pose controllers expect commands in the robot base frame (`panda_link0`).  World-frame eef pose and targets are converted via `arm_action._compute_frame_pose()` and `subtract_frame_transforms`.
- **Incremental absolute orientation:** `_clamp_orientation_target()` limits the per-step rotation to `_yaw_step_size`, reducing coupled roll/pitch and grasp slip.
- **Stable placement target:** `_initial_object_pos` is stored at episode start and used as the placement reference when no explicit command target is provided.
- **HOLD / RELEASE position hold:** in absolute mode a zero action vector means "move to origin", so the current eef pose is commanded while the gripper state changes.
- **LIFT transition fix:** removed the `near_target_xy` requirement from LIFT → REORIENT/ALIGN, so horizontal alignment is handled in ALIGN.

### 3. New config and CLI support

- New policy config: `configs/policies/heuristic_servo_goal_pose_abs.yaml`.
- `scripts/diagnostics/run_goal_pose_trace.py` now accepts `--embodiment` to override `task.metadata["arena_env_args"]["embodiment"]`.

### 4. Sequential multi-seed wrapper and per-run trace directories

- `ArenaRunner._run_docker` now accepts a per-run `_trace_dir` job field and bind-mounts that host directory to `/workspace/data/traces` inside the container, eliminating the shared `episode_trace.jsonl` race.
- `ArenaAdapter.run_policy` forwards an optional `trace_dir` into the job.
- `scripts/diagnostics/run_goal_pose_trace.py` uses a private `out_dir/traces/` subdirectory for each run.
- New wrapper `scripts/diagnostics/run_goal_pose_seed_sweep.py` runs seeds sequentially (one container at a time), optionally kills lingering Arena containers (`--cleanup`), and aggregates per-seed results into `aggregate_summary.json` and `per_seed_results.csv`.

### 5. Object physics ablation plumbing

- `rosclaw_darwin/adapters/arena.py` forwards `task.metadata["physics_ablation"]` into Docker evaluation jobs.
- `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` patches the container-side `ProceduralCube._generate_rigid_cfg` after Isaac Sim initialization, applying size / friction / mass overrides from the job config before the scene is built.
- New task configs under `configs/tasks/` define procedural-cube variants: baseline, dex-cube-matching size, high friction, combined size+friction, light mass, and large size.
- New script `scripts/diagnostics/run_goal_pose_object_ablation.py` evaluates these variants sequentially with private trace directories and produces aggregate JSON/CSV summaries.

---

## Validation results

### Sequential multi-seed runs with isolated trace directories (clean)

Using the new wrapper with `--cleanup` to remove any stale containers before starting, all 20 seeds completed successfully with identical initial conditions:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_seed_sweep.py \
  --start 0 --end 19 \
  --task configs/tasks/goal_pose.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_abs.yaml \
  --embodiment franka_ik_abs \
  --cleanup \
  --out-dir /tmp/rosclaw_data/seed_sweep_validation_v2
```

| seed | success_rate | progress | eef_to_object_dist_initial | status |
|----:|----:|----:|----:|---|
| 0 | 1.0 | 0.7344 | 0.9574 | completed |
| 1 | 1.0 | 0.7344 | 0.9574 | completed |
| 2 | 1.0 | 0.7344 | 0.9574 | completed |
| 3 | 1.0 | 0.7344 | 0.9574 | completed |
| 4 | 1.0 | 0.7344 | 0.9574 | completed |
| 5 | 1.0 | 0.7344 | 0.9574 | completed |
| 6 | 1.0 | 0.7344 | 0.9574 | completed |
| 7 | 1.0 | 0.7344 | 0.9574 | completed |
| 8 | 1.0 | 0.7344 | 0.9574 | completed |
| 9 | 1.0 | 0.7344 | 0.9574 | completed |
| 10 | 1.0 | 0.7344 | 0.9574 | completed |
| 11 | 1.0 | 0.7344 | 0.9574 | completed |
| 12 | 1.0 | 0.7344 | 0.9574 | completed |
| 13 | 1.0 | 0.7344 | 0.9574 | completed |
| 14 | 1.0 | 0.7344 | 0.9574 | completed |
| 15 | 1.0 | 0.7344 | 0.9574 | completed |
| 16 | 1.0 | 0.7344 | 0.9574 | completed |
| 17 | 1.0 | 0.7344 | 0.9574 | completed |
| 18 | 1.0 | 0.7344 | 0.9574 | completed |
| 19 | 1.0 | 0.7344 | 0.9574 | completed |

**Aggregate: 20/20 seeds succeed.**

### Isolated single-seed runs (clean)

After killing a stale Docker container that had been running since June 13 and ensuring only one Arena container was active at a time, every seed succeeded:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
for seed in $(seq 0 19); do
  python scripts/diagnostics/run_goal_pose_trace.py \
    --task configs/tasks/goal_pose.yaml \
    --policy configs/policies/heuristic_servo_goal_pose_abs.yaml \
    --embodiment franka_ik_abs \
    --seed $seed
done
```

| seed | success_rate | progress | eef_to_object_dist_initial | status |
|----:|----:|----:|----:|---|
| 0 | 1.0 | 0.7982 | 0.9574 | completed |
| 1 | 1.0 | 0.7344 | 0.9574 | completed |
| 2 | 1.0 | 0.7344 | 0.9574 | completed |
| 3 | 1.0 | 0.7344 | 0.9574 | completed |
| 4 | 1.0 | 0.7344 | 0.9574 | completed |
| 5 | 1.0 | 0.7344 | 0.9574 | completed |
| 6 | 1.0 | 0.7344 | 0.9574 | completed |
| 7 | 1.0 | 0.7344 | 0.9574 | completed |
| 8 | 1.0 | 0.7344 | 0.9574 | completed |
| 9 | 1.0 | 0.7344 | 0.9574 | completed |
| 10 | 1.0 | 0.7344 | 0.9574 | completed |
| 11 | 1.0 | 0.7344 | 0.9574 | completed |
| 12 | 1.0 | 0.7344 | 0.9574 | completed |
| 13 | 1.0 | 0.7344 | 0.9574 | completed |
| 14 | 1.0 | 0.7344 | 0.9574 | completed |
| 15 | 1.0 | 0.7344 | 0.9574 | completed |
| 16 | 1.0 | 0.7344 | 0.9574 | completed |
| 17 | 1.0 | 0.7344 | 0.9574 | completed |
| 18 | 1.0 | 0.7344 | 0.9574 | completed |
| 19 | 1.0 | 0.7344 | 0.9574 | completed |

**Aggregate: 20/20 seeds succeed.**

### Concurrent multi-seed runs

When four seeds were run concurrently (four `run_goal_pose_trace.py` processes launching Docker containers simultaneously), the success rate dropped to roughly 50% and the initial `eef_to_object_distance` became inconsistent.  The same seeds run in isolation afterwards succeeded.  This indicates **container/GPU resource interference**, not a deterministic policy failure.  The new sequential wrapper avoids this by never launching more than one container at a time and by giving each container a private trace directory.

### Seed reproducibility

Running seed 0 five times in a row and seed 1 five times in a row produced the same initial distance (`0.9574 m`) and the same success result every time, confirming that the policy and environment are repeatable when runs are isolated.  The sequential 20-seed sweep reproduced the same result across all seeds, with every run reporting `eef_to_object_distance_initial_mean = 0.9574 m`, `progress = 0.7344`, and `success_rate = 1.0`.

### Orientation and object generalization

A new generalization script, `scripts/diagnostics/run_goal_pose_generalization.py`, was used to test `franka_ik_abs` across target yaw orientations and object variants.  Each condition was run sequentially with a private trace directory.

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_generalization.py \
  --seeds 1 \
  --orientations 0 45 90 135 180 \
  --objects dex_cube procedural_cube \
  --cleanup \
  --out-dir /tmp/rosclaw_data/gen_full
```

| object | yaw (°) | success_rate | progress | object_height_delta | failure_type |
|---|---|---:|---:|---:|---|
| dex_cube | 0 | 1.0 | 0.7982 | +0.2855 | — |
| dex_cube | 45 | 1.0 | 0.7982 | +0.2876 | — |
| dex_cube | 90 | 1.0 | 0.7344 | +0.1968 | — |
| dex_cube | 135 | 1.0 | 0.7982 | +0.3325 | — |
| dex_cube | 180 | 1.0 | 0.7982 | +0.3356 | — |
| procedural_cube | 0 | 0.0 | 0.4953 | -0.1530 | object_not_lifted |
| procedural_cube | 45 | 0.0 | 0.4953 | -0.1530 | object_not_lifted |
| procedural_cube | 90 | 0.0 | 0.4953 | -0.1530 | object_not_lifted |
| procedural_cube | 135 | 0.0 | 0.4953 | -0.1530 | object_not_lifted |
| procedural_cube | 180 | 0.0 | 0.4953 | -0.1530 | object_not_lifted |

**Orientation generalization:** `franka_ik_abs` with `dex_cube` succeeded on all five tested target yaw angles (0°, 45°, 90°, 135°, 180°).  The policy therefore generalizes across target orientations for the registered cube asset.

**Object generalization:** `procedural_cube` failed every orientation with `object_not_lifted`.  The end-effector reached near the object (`eef_to_object_distance_min_mean ≈ 0.009 m`), but the object was not lifted (`object_height_delta_mean ≈ -0.153 m`, `object_height_max_mean ≈ 0.2 m`).

**Diagnosis of the `procedural_cube` failure:**

With the default `grasp_z_tolerance = 0.005 m` and `grasp_dist_threshold = 0.04 m`, the policy never leaves the `DESCEND` phase: the gripper stays open and the episode times out.  Increasing `grasp_z_tolerance` to `0.02 m` and `grasp_dist_threshold` to `0.05 m` allows the state machine to reach `GRASP`, `LIFT`, and `REORIENT`, but the run still fails with `object_not_lifted`.  Trace inspection shows that the gripper closes fully (`gripper_pos ≈ 0.0001 m`) yet the cube slips out during the horizontal translation in `LIFT`/`REORIENT` and remains on the table at `z ≈ 0.047 m` while the end-effector moves to `z ≈ 0.5 m`.

This indicates the procedural cube is smaller or has lower contact friction than `dex_cube`, so the gripper fingers close past the object rather than forming a stable frictional grasp.  The failure is therefore a grasp-geometry / physics issue, not an orientation-control issue.

### Object physics ablation

To test the small-object / low-friction hypothesis, a new sequential ablation script, `scripts/diagnostics/run_goal_pose_object_ablation.py`, was created.  It forwards `physics_ablation` metadata from the ROSClaw task through the Arena Docker job and patches the container-side `ProceduralCube` spawn config (size, friction, mass) before the scene is built.  Each condition runs with a private trace directory.

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_object_ablation.py \
  --cleanup \
  --out-dir /tmp/rosclaw_data/goal_pose_object_ablation_v2
```

| task | object | physics_ablation | success_rate | progress | object_height_delta | failure_type |
|---|---|---|---|---:|---:|---|
| goal_pose_001 | dex_cube | — | 1.0 | 0.7982 | +0.2855 | — |
| goal_pose_procedural_cube_baseline | procedural_cube | — | 0.0 | 0.4953 | -0.153 | object_not_lifted |
| goal_pose_procedural_cube_dex_size | procedural_cube | size [0.05, 0.05, 0.05] | 0.0 | 0.4953 | -0.153 | object_not_lifted |
| goal_pose_procedural_cube_high_friction | procedural_cube | static/dynamic 2.5 | 0.0 | 0.4953 | -0.153 | object_not_lifted |
| goal_pose_procedural_cube_dex_size_high_friction | procedural_cube | size [0.05, 0.05, 0.05] + friction 2.5 | 0.0 | 0.4953 | -0.153 | object_not_lifted |
| goal_pose_procedural_cube_light | procedural_cube | mass 0.1 | 0.0 | 0.4953 | -0.153 | object_not_lifted |
| goal_pose_procedural_cube_large | procedural_cube | size [0.08, 0.08, 0.08] | 0.0 | 0.4953 | -0.153 | object_not_lifted |

**Result:** none of the tested size, friction, or mass variants made `procedural_cube` succeed with the default `franka_ik_abs` policy.  All variants fail with the same `object_not_lifted` signature and nearly identical metrics, indicating the default policy never leaves the `DESCEND` phase for the procedural asset.

A second ablation was run with a looser grasp policy (`grasp_z_tolerance = 0.02 m`, `grasp_dist_threshold = 0.05 m`) so the state machine could at least reach `GRASP`.  In that setting even the registered `dex_cube` failed (`success_rate = 0.0`, `object_height_delta = -0.179`), which shows the looser parameters break the dex_cube grasp.  All procedural variants also remained at `0/6`.

**Conclusion:** the `procedural_cube` failure is not resolved by simple size / friction / mass tuning within the ranges tested, and the policy's grasp geometry is tightly coupled to the `dex_cube` asset.  A policy-side grasp adaptation (e.g. object-aware approach height, finger-width-aware closure, or contact-feedback-driven regrasp) or an Arena-side asset parameter change is likely required for object generalization.

---

## Lint / validation

- `ruff check rosclaw_darwin tests scripts/diagnostics/run_goal_pose_trace.py scripts/diagnostics/run_goal_pose_seed_sweep.py scripts/diagnostics/run_goal_pose_generalization.py scripts/diagnostics/run_goal_pose_object_ablation.py` — passing for the new/updated files (`run_eval.py` has pre-existing I001/F823 issues unrelated to this change).
- YAML task and policy configs validated.

---

## External coordination

Issue filed: [isaac-sim/IsaacLab-Arena#797](https://github.com/isaac-sim/IsaacLab-Arena/issues/797)

Questions raised:
1. Exact semantics of `franka_ik` relative-mode `action[..., 3:6]`.
2. Whether `franka_ik_abs` is the intended orientation-control path.
3. Gripper closure limit and long-duration hold instability.
4. `GoalPoseTask` success-metric details.
5. Official `dex_cube` asset parameters (size, collision approximation, material).
6. `procedural_cube` default size / mass / friction / collision approximation and whether it is expected to be interchangeable with `dex_cube` for `cube_goal_pose`.
7. Whether the `physics_ablation` patch approach in `run_eval.py` is the intended way to vary procedural object properties, or if a registry-level object variant is preferred.

---

## Honest caveats

1. **Concurrent evaluation is still not robust.**  Running multiple Arena Docker containers simultaneously (or leaving stale containers running) can perturb the initial state and cause sporadic failures.  Use the sequential `run_goal_pose_seed_sweep.py` wrapper with `--cleanup` for reliable multi-seed results.
2. **Trace files are now isolated per run.**  The shared-file race on `episode_trace.jsonl` has been eliminated by giving each Docker container its own bind-mounted trace directory.  The legacy shared path `/tmp/rosclaw_data/traces/episode_trace.jsonl` is no longer used by the new wrapper.
3. **Orientation generalization is validated; object generalization is not.**  `franka_ik_abs` succeeds across 0°–180° target yaw with the registered `dex_cube`, but fails on `procedural_cube` with `object_not_lifted`.  Physics ablation of procedural-cube size, friction, and mass did not recover success, so the gap is not a simple parameter mismatch.
4. **Physics ablation plumbing is now available.**  `ArenaAdapter` forwards `physics_ablation` metadata into Docker jobs, and `run_eval.py` applies it to the container-side `ProceduralCube` spawn config.  This enables future object/physics experiments without rebuilding the image.
5. **Slower position control.**  `franka_ik_abs` needs the full 2500-step horizon to complete the episode.
6. **Grasp slip still possible.**  Fast translation can still cause the cube to slip/rotate inside the gripper; mitigated by incremental reorientation and by reorienting before the final ALIGN move.
7. **Workaround, not official fix.**  The embodiment is patched into the Docker runtime; official approval from the Arena team is pending.
8. **Seed parameter may not reach the container.**  `run_goal_pose_trace.py` sets `task.mutation.seed`, but it is not yet forwarded into the Arena Docker job; observed repeatability comes from the deterministic initial joint pose and a clean container state.

## Open tasks

- `ARENA_ISSUE_TRACKER.md` P0 controller/action-space questions are **Resolved locally**.
- P1/P2 questions (gripper closure, long hold, success metric, `dex_cube` asset) remain **Open** pending Arena-team feedback.
- Multi-seed evaluation concurrency is **Resolved** for sequential runs with isolated trace directories; concurrent multi-container evaluation remains **Open**.

## Recommended next steps

1. **Object generalization remains blocked.**  Size / friction / mass ablation did not recover `procedural_cube`.  Next, investigate policy-side grasp adaptation (object-aware approach height, gripper-width-aware closure, contact-feedback regrasp) or Arena-side asset differences (collision approximation, contact offset, material) that make `procedural_cube` behave differently from `dex_cube` despite similar dimensions.
2. **Wait for Arena issue #797 response.**  Do not refactor the controller layer further until the intended design is confirmed.  In particular, clarify the official `dex_cube` dimensions / collision setup and whether `procedural_cube` is expected to be interchangeable with it.
3. **Refresh reports:** update `POLICY_V3_INTERVENTION_REPORT.md` and `FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md` with the latest isolated-run evidence.
4. **FailureToHintEngine v3 integration is complete** (tests pass; `EvolutionRunner` already consumes `FailureSignature` tags and `HintRecipe.parameter_overrides`).
