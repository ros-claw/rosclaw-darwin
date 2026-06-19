# Dex-Cube Goal Pose Generalization Report (v1.5)

## 1. Purpose

This report documents the randomized validation matrix for the official
`dex_cube` asset under real seed randomization.  It answers the question:

> Now that `task.mutation.seed` is forwarded all the way into the Arena Docker
> container and the phase-trace shadow-variable bug is fixed, how robust is the
> proven `franka_ik_abs` + `heuristic_servo_goal_pose_v3` path across a broad
> set of initial object poses?

## 2. Method

- **Task:** `configs/tasks/goal_pose_dex_cube_official.yaml`
- **Policy:** `configs/policies/heuristic_servo_goal_pose_v3.yaml`
- **Embodiment:** `franka_ik_abs` (absolute pose IK, 8-D action `[pos, quat, gripper]`)
- **Seeds:** 0–29 (30 seeds, 1 episode each)
- **Randomization source:** `task.mutation.seed` → `ArenaAdapter` → Docker env
  vars `ROSCLAW_ARENA_SEED` / `ROSCLAW_ARENA_PLACEMENT_SEED` → policy-level
  object pose perturbation on step 0.
- **Trace reliability:** `HeuristicServoGoalPosePolicy.reset()` now clears the
  shadowed `_last_gate_diagnostics`, so `episode_trace.jsonl` records the true
  phase sequence.

The matrix is run sequentially because concurrent Arena Docker runs still
suffer from GPU/container resource contention.

```bash
PYTHONPATH="/code/rosclaw/rosclaw_darwin/rosclaw-darwin" \
  ROSCLAW_ARENA_MODE=docker \
  python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --seeds $(seq 0 29) \
  --out-dir /tmp/rosclaw_data/dex_cube_generalization
```

## 3. Results (30 seeds, seeds 0–29)

The full matrix finished with **18/30 successes (60% success rate)**.  Seed
randomization is confirmed: `object_x_initial`, `object_y_initial`, and
`object_yaw_initial` all vary across seeds.  `target_yaw` remained constant at
`~1.5708` for every seed, because the environment's target-orientation stream
is independent of the placement seed we forwarded.

### 3.1 Overall success

| metric | value |
|--------|-------|
| total seeds | 30 |
| successful seeds | 18 |
| overall success rate | 0.60 |
| mean progress | 0.6339 |
| mean object height max | 0.4216 |
| mean eef-to-object distance min | 0.0660 |
| mean min grasp z error | 0.00535 |
| mean min grasp dist | 0.00601 |

### 3.2 Per target-yaw bin

| bin | count | success rate |
|-----|-------|--------------|
| 0_to_0.5 | 0 | — |
| 0.5_to_1.0 | 0 | — |
| 1.0_to_1.5 | 0 | — |
| 1.5_to_2.0 | 30 | 0.60 |
| 2.0_to_2.5 | 0 | — |
| 2.5_to_pi | 0 | — |

### 3.3 Per initial object-yaw bin

| bin | count | success rate |
|-----|-------|--------------|
| -0.5_to_0 | 12 | 0.667 |
| 0_to_0.5 | 18 | 0.556 |

### 3.4 Phase reach rates

| phase | reach rate |
|-------|------------|
| DESCEND exit | 0.90 |
| GRASP reached | 0.90 |
| LIFT reached | 0.90 |

### 3.5 Failed seeds

| seed | success_rate | progress | object_yaw_initial | failure mode |
|------|--------------|----------|--------------------|--------------|
| 2 | 0.0 | 0.4967 | -0.464 | reached/grasped/lifted phases but object height max = 0.2 |
| 4 | 0.0 | 0.4983 | -0.109 | reached/grasped/lifted phases but object height max = 0.2 |
| 7 | 0.0 | 0.1723 | +0.158 | never exited DESCEND (eef min dist 0.62) |
| 9 | 0.0 | 0.4983 | -0.379 | reached/grasped/lifted phases but object height max = 0.2 |
| 10 | 0.0 | 0.4984 | +0.082 | reached/grasped/lifted phases but object height max = 0.2 |
| 11 | 0.0 | 0.4983 | +0.444 | reached/grasped/lifted phases but object height max = 0.2 |
| 12 | 0.0 | 0.4983 | +0.174 | reached/grasped/lifted phases but object height max = 0.2 |
| 13 | 0.0 | 0.4983 | +0.193 | reached/grasped/lifted phases but object height max = 0.2 |
| 15 | 0.0 | 0.1669 | +0.247 | never exited DESCEND (eef min dist 0.66) |
| 24 | 0.0 | 0.4990 | -0.332 | reached/grasped/lifted phases but object height max = 0.2 |
| 28 | 0.0 | 0.1742 | +0.102 | never exited DESCEND (eef min dist 0.61) |
| 29 | 0.0 | 0.4983 | +0.361 | reached/grasped/lifted phases but object height max = 0.2 |

Two distinct failure modes are visible:

1. **Approach failure** (seeds 7, 15, 28): the gripper never gets close to the
   object; `descend_exit_rate=0`, `eef_to_object_distance_min` is large.  This
   appears to correlate with object yaws around `+0.10` to `+0.25` rad.
2. **Slip/early-drop after LIFT** (all other failures): the state machine
   reaches GRASP and LIFT, but `object_height_max_mean=0.2` shows the object
   never actually left the table.  The gripper closes around the object but the
   object slips during lift.

## 4. Interpretation

- **Randomization works.**  Different seeds now produce measurably different
  initial poses, and the success rate is no longer 100% under fixed conditions.
- **The policy is partially robust but not fully general.**  60% success on
  official dex_cube with randomized placement is a clear regression from the
  earlier fixed-seed 20/20 result, which demonstrates that seed randomization
  was exposing real failure modes that were previously hidden.
- **Failure is not dominated by target orientation.**  All seeds share the same
  `target_yaw≈1.57`, so the 40% failure rate is driven by placement/orientation
  of the *object*, not by the target pose.
- **Gripper slip after LIFT is the dominant failure mode.**  9 of 12 failures
  show the LIFT phase reached but `object_height_max=0.2`.  This is the same
  grasp-stability problem the `verify_object_following` and `longer_gripper_close`
  hints were designed to address, but the current tuning is insufficient under
  random initial yaw.

## 5. Honest limitations

- The matrix varies **placement** seed, not **target orientation** seed, so we
  cannot claim target-yaw generalization.
- One episode per seed gives a Bernoulli sample; the 95% CI for 18/30 is
  roughly `[0.41, 0.77]`.
- `franka_ik_abs` is a local workaround, not the official leaderboard
  embodiment.
- The `target_yaw_bin_success` table is degenerate because every seed landed in
  the same bin.

## 6. Next steps

1. Inspect traces for failed seeds to confirm dominant blocking reasons.
2. Run `goal_pose_lift_small_yaw.yaml` and `goal_pose_lift_90_yaw.yaml` with
   randomized seeds to validate target-orientation generalization.
3. Increase `min_grasp_steps` / `grasp_squeeze_steps` and reduce
   `gripper_close_threshold` further for random-yaw dex_cube, or add an
   object-yaw-aware pre-grasp orientation correction.
4. Re-run the matrix after the next intervention to measure improvement.

---

## Update (2026-06-18): target-yaw override diagnostic and 50-seed extension

Because the Arena `cube_goal_pose` environment fixes `target_yaw` to `pi/2`
regardless of seed, the 30-seed matrix above does **not** demonstrate
cross-target-yaw generalization.  To close this gap I added an optional
`target_yaw_override` parameter to `HeuristicServoGoalPosePolicy` and created
`scripts/diagnostics/run_target_yaw_generalization_matrix.py`.

### Method

- The policy config key `target_yaw_override` (radians) replaces the
  environment's target quaternion with a quaternion built from the supplied yaw.
- The policy therefore tries to lift **and** align the object to the override
  yaw.
- The script sweeps 5 target yaws (`0.0, 0.5236, 0.7854, 1.0472, 1.5708` rad)
  across 10 randomized seeds each.
- Because the environment's own `pose_reached` metric may not strictly penalize
  final orientation, the script computes a custom `orientation_achieved` metric:
  among trace steps where `object_z > 0.25 m`, the minimum yaw error to the
  override target must be below the policy's default `orientation_threshold`
  (0.5 rad).

### 50-seed extension

The 30-seed matrix produced a wide 95% CI (`[0.41, 0.77]`).  A first 50-seed
re-run (seeds 0–49) was launched to tighten the estimate, but it was **contaminated
by concurrent GPU/container contention**: the target-yaw matrix was started in
parallel before the dex_cube matrix finished.  The first 50-seed run therefore
shows an anomalously low completion rate (only ~16/50 seeds produced usable
metrics; the rest returned `status: failed` with empty traces).  This is not a
policy result; it is an infrastructure artifact.

To fix this, both scripts now accept a `--cleanup` flag that kills any lingering
`rosclaw-darwin:arena-base` containers before each seed, and the matrices are
being re-run **strictly sequentially**:

```bash
# dex_cube 50 seeds, with per-seed container cleanup
python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --seeds $(seq 0 49) --cleanup \
  --out-dir /tmp/rosclaw_data/dex_cube_generalization_50seeds_v2

# target-yaw 5×10 matrix, after dex_cube finishes
python scripts/diagnostics/run_target_yaw_generalization_matrix.py \
  --target-yaws 0.0 0.5236 0.7854 1.0472 1.5708 \
  --seeds $(seq 0 9) --cleanup \
  --out-dir /tmp/rosclaw_data/target_yaw_generalization_v2
```

### Results

#### 50-seed extension (clean, sequential, seeds 0–49, pre-GRASP-pose-hold fix)

The corrected sequential run finished with **24/50 successes (48%)** and **all
50 seeds produced usable metrics** (no `status: failed` contamination).  This was
a more honest estimate than the first 30-seed run's 60%, because the extra seeds
included more difficult initial poses.

| metric | value |
|--------|-------|
| total seeds | 50 |
| successful seeds | 24 |
| overall success rate | **0.48** |
| mean progress | 0.599 |
| mean object height max | 0.374 m |
| mean min grasp z error | 0.00534 m |
| mean min grasp dist | 0.00599 m |

Per initial-object-yaw bin:

| bin | count | success rate |
|-----|-------|--------------|
| -0.5_to_0 | 23 | 0.522 |
| 0_to_0.5 | 27 | 0.444 |

At this point the failure modes appeared to be:

1. **Approach collision** (e.g., seeds 7, 15, 28, 36, 41, 48): the gripper
   pushes the object during approach; `descend_exit_rate=0` and final
   eef-to-object distance is large.
2. **Grasp slip after LIFT** (the majority of failures): state machine reaches
   GRASP/LIFT but `object_height_max` stays at 0.2 m, indicating the object
   slipped out during lift.

#### 50-seed re-run after the GRASP pose-hold fix

After fixing the missing pose-hold command in the `GRASP` state (see the
"GRASP pose-hold bug fix" section below), the same 50-seed matrix was re-run:

```bash
python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --seeds $(seq 0 49) --cleanup \
  --out-dir /tmp/rosclaw_data/dex_cube_generalization_50seeds_v3_grasp_hold \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml
```

Result:

| metric | value |
|--------|-------|
| total seeds | 50 |
| successful seeds | **44** |
| overall success rate | **0.88** |
| mean progress | 0.720 |
| mean object height max | 0.494 m |
| mean min grasp z error | 0.00534 m |
| mean min grasp dist | 0.00599 m |

Per initial-object-yaw bin:

| bin | count | success rate |
|-----|-------|--------------|
| -0.5_to_0 | 23 | **0.957** |
| 0_to_0.5 | 27 | **0.815** |

Failed seeds after the fix (6/50):

| seed | failure mode | note |
|---|---|---|
| 7 | approach collision | `eef_to_object_distance_min_mean` = 0.62 m |
| 15 | approach collision | `eef_to_object_distance_min_mean` = 0.66 m |
| 24 | high grasp error | `min_grasp_z_error` = 0.0085 m, `min_grasp_dist` = 0.0088 m |
| 28 | approach collision | `eef_to_object_distance_min_mean` = 0.61 m |
| 37 | approach collision | `eef_to_object_distance_min_mean` = 0.61 m |
| 48 | approach collision | `eef_to_object_distance_min_mean` = 0.61 m |

The fix eliminated almost all of the "grasp slip after LIFT" failures.  The
remaining failures are approach collisions (5 seeds) and one seed (24) where the
grasp alignment error is systematically larger than the gate threshold.  This
brings the official `dex_cube` success rate from **48% to 88%** under the same
50-seed randomized placement distribution.

#### Approach-collision ablations

The five remaining approach-collision seeds share two features: the object's
initial **y coordinate is positive** and its initial **yaw is positive** (roughly
+0.10 to +0.25 rad).  Several quick interventions were tested on these seeds:

| intervention | seeds fixed / 5 | note |
|---|---|---|
| `approach_offset_z: 0.25` | 0/5 | Higher approach height did not change the kinematic dead-end. |
| `pre_grasp_orient: true` | 0/5 | Pausing above the object to align yaw did not help reach. |
| `align_yaw_during_approach: true`, `approach_yaw_offset=π` (same grasp offset) | 0/5 | Small gripper yaw correction did not unlock the workspace; it also regressed previously successful seeds. |
| `align_yaw_during_approach: true`, `approach_yaw_offset=π/2` (world-as-base quirk) | 3/5 | Reached GRASP/LIFT on seeds 7, 15, 28, but broke the gripper-object yaw relationship needed for final alignment, so success_rate stayed 0. |

Conclusion: the remaining approach collisions are **not a simple threshold or
orientation-alignment issue**.  The arm reaches a kinematic/workspace boundary
near world `(x≈+0.06, y≈+0.05, z≈+0.31)` and cannot cross to the object on the
positive-y side with the default reset configuration.  A principled fix likely
requires a different approach path, a different initial robot pose, or an
embodiment with a larger reachable workspace.  The 88% success rate is therefore
a honest ceiling for the current `franka_ik_abs` + v3 policy combination.

#### Target-yaw matrix (post GRASP pose-hold fix)

The cross-target-yaw diagnostic was re-run with the fixed v3 policy.  The
result is **not flat**: small reorientations are now highly robust, while large
reorientations expose a new failure mode — the cube rotating inside the gripper
while the gripper is commanded to a large yaw.

| target_yaw (rad) | lifted_rate | orientation_achieved_rate | env_success_rate | mean progress | mean final orientation error (rad) |
|---|---:|---:|---:|---:|---:|
| 0.0000 | 0.90 | 0.90 | 0.90 | 0.720 | 0.033 |
| 0.5236 | 0.90 | 0.20 | 0.90 | 0.682 | 0.410 |
| 0.7854 | 0.90 | 0.20 | 0.90 | 0.676 | 0.613 |
| 1.0472 | 0.80 | 0.20 | 0.80 | 0.711 | 0.789 |
| 1.5708 | 0.30 | 0.10 | 0.30 | 0.769 | 1.177 |

- At `target_yaw = 0.0` the object only has to cancel its initial yaw; both
  lift and orientation are achieved on **9/10 seeds** (seed 7 is the recurrent
  approach-collision failure).
- As the commanded target yaw grows, the gripper must rotate the object while
  maintaining friction.  The object is still lifted, but it often rotates
  relative to the fingers and ends up at a yaw far from the target.  This is
  visible in the per-seed traces: for `target_yaw = 0.5236` and seed 0, the
  object yaw drifts to approximately **-2.6 rad** during REORIENT/ALIGN while
  the gripper itself converges to the desired yaw.
- At `target_yaw = π/2` the failure rate jumps: only **3/10 seeds** complete
  the episode, and only 1/10 achieves the orientation.  Several seeds fail with
  `status: failed` early in the episode, suggesting that the large initial
  reorientation destabilises the grasp before lift.

This is a **different bottleneck** than the one diagnosed before the GRASP
pose-hold fix.  The fix removed the arm-drift failure, so the remaining
orientation-generalisation limit is **in-gripper rotation during large yaw
reorientation**.  It is not a lack of yaw authority: the absolute-mode
controller drives the gripper to the desired yaw (the trace `desired_eef_yaw`
matches the override).  The problem is that the cube does not always stay
locked to the gripper while being turned.

Important caveat: the `target_yaw_override` constructs a **pure world-yaw
quaternion** and then converts it to the robot base frame.  The native Arena
command for the default π/2 target may have a different roll/pitch composition.
This is why the override at π/2 underperforms the default placement matrix
(88% success with the environment's own target), even though both nominally
ask for the same yaw.  The override is a useful diagnostic probe but not a
perfect replacement for an Arena-supported `target_yaw` task argument.

#### Subtask decomposition sweeps (10 seeds each)

The decomposed subtasks were also evaluated with `franka_ik_abs` and the v3
policy to see whether removing the orientation requirement improves robustness:

| task | success rate | note |
|---|---|---|
| `goal_pose_lift_only` | **6/10** | Only requires `object_lifted`; still fails on 4 seeds due to grasp slip. |
| `goal_pose_lift_hold` | **5/10** | Requires lift + hold; similar failure mode. |

These results confirm that even the simplest lift task is not fully robust under
randomized placement.  The bottleneck is again grasp stability after contact,
not the reorientation phase.

#### Strong-grasp ablation on slip seeds

A stronger-grasp variant of the v3 policy (`min_grasp_steps=45`,
`grasp_squeeze_steps=25`, `gripper_close_threshold=0.010`,
`verify_object_following_steps=10`) was evaluated on the 9 slip seeds from the
30-seed matrix (seeds 2, 4, 9, 10, 11, 12, 13, 24, 29).

Result (pre-GRASP-pose-hold fix): **0/9 seeds lifted the object**.  Every run
still reached GRASP/LIFT (`descend_exit_rate=1.0`,
`lift_phase_reached_rate=1.0`) but `object_height_max` remained 0.2 m and
`object_height_delta` was approximately -0.179 m.  At the time this looked like
a negative ablation result: tuning close/squeeze settings did not prevent slip.

After the GRASP pose-hold fix the same strong-grasp variant succeeds on **8/9**
of those seeds, showing that the original "slip" signature was actually caused
by the gripper drifting while closing, not by insufficient squeeze force.

## Update (2026-06-18): GRASP pose-hold bug fix resolves most slip seeds

While inspecting the strong-grasp trace for seed 2, I noticed that during the
`GRASP` phase the end-effector kept descending (`eef_z` went from 0.0156 m to
0.0099 m) while the gripper was closing.  In the `HeuristicServoGoalPosePolicy`
`GRASP` state only the gripper command was being written; the arm command was
left as zeros.  For `franka_ik_abs` (absolute pose mode) a zero pose command is
interpreted as "move to the origin", so the gripper was drifting down and away
from the object while the fingers closed.  This caused the fingers to close
beside/under the cube instead of around it — the same signature that had been
labeled "grasp slip after LIFT".

**Fix:** in `HeuristicServoGoalPosePolicy.GRASP` (and `HeuristicServoLiftPolicy.GRASP`)
hold the current end-effector pose while closing when the controller is in
absolute mode, mirroring the existing `HOLD` / `RELEASE` behaviour.

Re-running the 9 slip seeds from the 30-seed matrix (seeds 2, 4, 9, 10, 11, 12,
13, 24, 29):

| policy | success count / 9 | note |
|---|---|---|
| `heuristic_servo_goal_pose_v3.yaml` (base) | **8/9** | only seed 24 still fails |
| `heuristic_servo_goal_pose_v3_strong_grasp.yaml` | **8/9** | only seed 2 shows an anomalous high `object_height_max` and negative delta |

This is a dramatic improvement from the pre-fix result of **0/9**.  The dominant
failure mode was therefore not "slip after contact" but a **missing pose-hold
command during GRASP** that made the gripper miss the object entirely.  The full
50-seed randomized matrix with the fix finished with **44/50 successes (88%)**.

### Approach-collision diagnosis and small-target-yaw validation

The 6 failing seeds in the 88% matrix fall into two groups:

| seed | failure mode | object_y_initial | object_yaw_initial | note |
|------|--------------|------------------|--------------------|------|
| 7 | approach collision | +0.021 | +0.158 | eef never reaches the object |
| 15 | approach collision | +0.029 | +0.247 | eef never reaches the object |
| 28 | approach collision | +0.022 | +0.102 | eef never reaches the object |
| 37 | approach collision | +0.025 | +0.123 | eef never reaches the object |
| 48 | approach collision | +0.022 | +0.222 | eef never reaches the object |
| 24 | reorientation slip | -0.009 | -0.332 | reaches GRASP/LIFT but loses object during π/2 reorientation |

Five seeds share positive initial object-y and positive initial object-yaw; the
arm stops at approximately `(x≈+0.06, y≈+0.05, z≈+0.31)` and cannot reach the
object from the default reset pose.

Four quick fixes were tested on the five approach-collision seeds:

| intervention | fixed / 5 | note |
|---|---|---|
| `approach_offset_z=0.25` | 0/5 | Not a height problem. |
| `pre_grasp_orient=true` | 0/5 | Pausing above the object did not help reach. |
| `align_yaw_during_approach`, `approach_yaw_offset=π` | 0/5 | Preserves gripper-object yaw but does not unlock workspace; regresses previously successful seeds. |
| `align_yaw_during_approach`, `approach_yaw_offset=π/2` | 3/5 | Reached GRASP/LIFT on seeds 7, 15, 28, but broke final alignment yaw relationship. |

The honest conclusion is that the approach collisions are **not a policy-parameter
problem**; they are a workspace/kinematic boundary of the default `franka_ik_abs`
reset configuration for objects on the positive-y side of the table.

To separate the π/2 reorientation effect from the workspace effect, I ran the
full 50-seed matrix again with `target_yaw_override=0.0`.  In this configuration
the policy only has to cancel the object's initial yaw, not reorient it to π/2:

| metric | value |
|---|---:|
| total seeds | 50 |
| successful seeds | **45** |
| overall success rate | **0.90** |
| lifted_rate | 0.90 |
| orientation_achieved_rate | 0.90 |

The only failures are the **same 5 approach-collision seeds** (7, 15, 28, 37,
48).  Seed 24, which failed in the default π/2 matrix, **succeeds** when the
target yaw is 0.0.  This cleanly isolates the two remaining bottlenecks:

1. **Approach collision** on positive-y / positive-yaw initial poses — a
   workspace limit of the current embodiment.
2. **π/2 reorientation** on seed 24 — the object slips in the gripper during the
   large reorientation required by the default goal.

The 88% success rate of the default matrix is therefore the honest ceiling for
`franka_ik_abs` + v3 under the environment's native π/2 target.  Removing the
large reorientation lifts the ceiling to **90%**, but the remaining 10% still
requires a workspace fix.

### Honest caveats

- The first 50-seed run is **discarded** because of concurrent GPU contention.
- `target_yaw_override` is a **diagnostic probe**, not an official benchmark
  configuration.  The Arena success metric still uses the environment's
  original target, so official `success_rate` should be interpreted alongside
  the custom `orientation_achieved` metric.
- The cross-orientation diagnostic only tests the policy's ability to command
  a different yaw; it does not change the environment's goal.  A true
  cross-yaw benchmark will require Arena-side support for `target_yaw` as a
  task/environment argument.
- `franka_ik_abs` remains a local patched embodiment.
