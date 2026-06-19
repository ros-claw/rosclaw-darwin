# ROSClaw-Darwin Arena Issue Tracker

This document consolidates every open question, blocker, and follow-up item that
requires input from the IsaacLab-Arena team, simulation experts, or a deeper
embodiment-level investigation.  It is derived from the physical-diagnosis
reports in `reports/` and the external review package in
`external_reviews/goal_pose_diagnosis_pack/`.

---

## Executive Summary

| Priority | Item | Status | Owner |
|---|---|---|---|
| P0 | `franka_ik` relative-mode `action[..., 3:6]` has cross-coupled rotational response | **Resolved locally** | ROSClaw |
| P0 | Correct way to command end-effector yaw/orientation | **Resolved locally** | ROSClaw |
| P1 | Gripper blocked-close limit (~0.024) vs. expected `dex_cube` geometry | **Open** | Arena team |
| P1 | Long-duration hold instability after ~1600 steps | **Open** | Physics tuning / Arena team |
| P2 | Procedural cube fallback vs. intended `dex_cube` asset | **Submitted** — [IsaacLab-Arena#807](https://github.com/isaac-sim/IsaacLab-Arena/issues/807) | Arena team |
| P2 | GoalPose success metric semantics (stationarity requirement?) | **Open** | Arena team |
| P2 | GoalPose target yaw is fixed at π/2 for all seeds | **Open** | Arena team |
| P2 | Official working baseline for `cube_goal_pose` | **Open** | Arena team |
| P2 | GoalPose object spawns far from robot and falls/slides before grasp | **Open** | Arena team |

---

## 1. Controller / Action Space (P0)

### 1.1 What is the exact semantic of `action[..., 3:6]` in `franka_ik` relative mode?

Configuration:

```python
DifferentialInverseKinematicsActionCfg(
    command_type="pose",
    use_relative_mode=True
)
```

Questions:

1. Is `action[..., 3:6]` a quaternion delta, rotation vector, Euler-angle delta,
   or something else?
2. Why does commanding pure values on `action[..., 3]`, `action[..., 4]`,
   `action[..., 5]` produce **cross-coupled** end-effector rotation rather than
   clean world-yaw control?
3. Why do `action[..., 3]` and `action[..., 4]` also produce **translational**
   motion alongside rotation?

Evidence:

- `reports/ROTATIONAL_ACTION_CALIBRATION_REPORT.md` — after fixing the
  `source_quat_w` / `quat_w` reading bug, all three rotational axes produce
  end-effector rotation, but the mapping to world roll/pitch/yaw is
  cross-coupled.
- `reports/ACTION_RESPONSE_CALIBRATION_REPORT.md` — positional axes are heavily
  damped and body-frame sign-flipped.

### 1.2 How should end-effector yaw/orientation be commanded?

**Status (2026-06-16): Resolved locally; external clarification requested in [isaac-sim/IsaacLab-Arena#797](https://github.com/isaac-sim/IsaacLab-Arena/issues/797).**

The working approach for `cube_goal_pose` is:

1. Register/use the patched `franka_ik_abs` embodiment (`use_relative_mode=False`,
   `scale=1.0`, 8-dim action: `[pos_x, pos_y, pos_z, quat_x, quat_y, quat_z,
   quat_w, gripper]`).
2. Convert all world-frame poses to the robot base frame before writing them
   into the action.
3. Command the absolute target quaternion in `(x, y, z, w)` order.
4. Clamp the rotation step per control tick to avoid coupled roll/pitch and
   grasp slip.

See `reports/FRANKA_IK_ORIENTATION_INVESTIGATION_REPORT.md` section 9 for the
full implementation and 5-seed validation (5/5 success).

Original questions (kept for reference):

Options we can test once clarified:

1. **Absolute quaternion target** — write target quaternion into `action[..., 3:7]`
   with `use_relative_mode=False`.
2. **Absolute pose target** — write full 7-DoF pose target with `use_relative_mode=False`.
3. **Joint-space controller** — switch to `franka_joint_pos` or similar and control
   orientation via joint commands.

Questions:

4. Which of the above is the intended/recommended way to control orientation for
   `cube_goal_pose`?
5. Does the 8-dimensional action space support a 7-DoF pose target plus gripper?
6. If absolute quaternion mode works, what is the correct ordering of the four
   quaternion components (`w, x, y, z` vs. `x, y, z, w`)?
7. Is there a maximum angular-step limit or internal clamping we should know about?

### 1.3 Is the observed behavior a bug or a configuration mismatch?

Questions:

8. Is zero rotational authority expected for the default Docker embodiment?
9. Are there environment variables, cfg flags, or asset variants that enable
   rotation?
10. Could the action scaling (`action_scale` / `action_clamp`) be damping
    rotational commands to zero?

---

## 2. Gripper / Object / Grasp (P1)

### 2.1 Gripper closure limit

Observation:

- Empty close reaches `gripper_pos ≈ 0.00012`.
- Cube-blocked close stops at `gripper_pos ≈ 0.024` and cannot go lower even with
  extended squeeze time.

Questions:

11. What is the physical meaning of `gripper_pos`? 0 = fully closed, 0.04 = fully
    open?
12. Is 0.024 the expected joint value when fingers are blocked by a 0.05 m thick
    cube?
13. Is the gripper force/torque limit preventing tighter closure?
14. How can we increase gripper closure force for long-duration holds?

### 2.2 Grasp-success proxy

Current policy uses `gripper_pos < threshold`.  This is unreliable because:

- The threshold is task/geometry dependent.
- Long holds can slip even when `gripper_pos` remains at the blocked value.

Questions:

15. Is there an official grasp-success proxy (contact sensors, finger force,
    object-eef distance stability)?
16. Should the success criterion include object-following verification rather
    than gripper position?

### 2.3 Object asset

Observation:

- `dex_cube` is not available in the local Docker runtime; we fall back to
  `procedural_cube` with size `(0.05, 0.1, 0.1)` m and mass `0.2` kg.
- Asset resolution (Sprint 0) now detects this substitution: the requested
  `procedural_cube` loads with scene key `"object"`, triggering
  `fallback_reason=loaded_object_instead_of_procedural_cube`.
- The official `dex_cube` task (`goal_pose_dex_cube_official.yaml`) correctly
  resolves `loaded_object=dex_cube` and is marked `official_asset=True`.

Questions:

17. Is the procedural fallback consistent with the intended `dex_cube`?
18. What are the official `dex_cube` size, mass, inertia, and friction parameters?
19. Should we register a new asset variant instead of relying on the fallback?
20. Is the object initial pose (`z ≈ 0.021` after settle) correct, or should it be
    placed higher/closer to the gripper?
21. Why does the procedural cube spawn with scene key `"object"` instead of
    `procedural_cube`?  Can the key be made deterministic?

### 2.4 GoalPose object initial pose

Observation (paired trace diff, 2026-06-17):

- The object spawned at approximately `(-0.5, 0, 0.2)` m, while the end-effector
  starts near `(0.45, -0.03, 0.25)` m.
- The object falls and slides to `(-0.15, -0.43, 0.02)` m before the gripper can
  reach it.
- Even the official `dex_cube` failed to reach `GRASP` under these initial
  conditions.
- All five tested seeds produced identical initial poses, suggesting that seed
  variation did not affect the object spawn position in this run.

Questions:

22. Is the `GoalPoseTask` command target sampled far from the robot on purpose?
23. Can the object be spawned on the table (`z ≈ 0.05`–`0.07` m) and closer to
    the robot's workspace to match the `dex_cube` 20/20 validation conditions?
24. How is the object initial pose related to the sampled command target?
25. Why did varying `task.mutation.seed` not change the object spawn position?

---

## 3. Task / Success Metric (P2)

Observation:

- `GoalPoseTask` success requires `object_z ∈ [0.2, 1.0]` and object yaw error
  `< 0.2` rad.
- Our policy can lift to `object_z ≈ 0.33` but still reports `success_rate = 0`.

Questions:

21. Does `GoalPoseTask` terminate early only on height + yaw, or does it also
    require the object to be stationary?
22. Is there a minimum hold duration or a "pose reached for N steps" requirement?
23. Is the target yaw `π/2` (90°) measured in world frame or object frame?
24. What is the tolerance on position (`success_threshold`) vs. orientation
    (`orientation_threshold`) and are they independent?
25. Can/should the success tolerance be relaxed for early validation?
26. Does `cube_goal_pose` expose an argument (environment or task config) to set a
    non-default target yaw?  The observed `target_yaw` is fixed at `π/2` for all
    seeds, which prevents true cross-orientation benchmarking without a local
    policy-level override.
27. If the target yaw is fixed, is `pose_reached` evaluated against that fixed yaw
    or does the success metric primarily depend on lift height / position?

---

## 4. Physics / Material (P1)

Observation:

- v3 policy holds the object ~9× longer than baseline but eventually slips after
  ~1600 steps even though `gripper_pos` stays at ~0.024.
- Physics ablation (high friction, smaller cube, lighter cube) did not solve yaw
  failure.

Questions:

26. If the cube slips inside the gripper during reorientation or long hold,
    which parameters should be tuned first?
    - Gripper force limit
    - Finger friction coefficient
    - Object friction coefficient
    - Solver iterations / contact stiffness
27. Can we change the procedural cube's physics material/size/mass at runtime for
    diagnostic ablations?
28. What is the recommended friction value for a stable pinch grasp of the cube?
29. Does IsaacLab-Arena use TGS or PGS solver?  Does increasing substeps help
    contact stability?
30. Are there known drift/relaxation effects in long-duration holds (e.g. contact
    force saturation, joint integral windup)?

---

## 5. Known Working Baselines (P2)

Questions:

31. Is there an official teleop, heuristic, or learned policy that can solve
    `cube_goal_pose` with `franka_ik`?
32. Can the Arena team provide a reference trace or policy config for
    `cube_goal_pose`?
33. Is `cube_goal_pose` expected to be solvable with the default `franka_ik`
    relative-mode action space?
34. Are there other tasks in the benchmark suite that require orientation control
    and do work?  If so, what controller/action-space do they use?

---

## 6. Diagnostics We Can Run Locally (No External Input Required)

While waiting for Arena-team answers, the following experiments can continue:

### 6.1 Absolute quaternion orientation calibration

Test whether `action[..., 3:7]` with the controller in absolute pose mode produces
controlled end-effector rotation.

Script:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_rotational_action_calibration.py \
  --absolute-mode --steps 30 --target-yaw-delta 0.785398 \
  --out-dir /tmp/rosclaw_data/calibrations/rotational_absolute
```

Expected outcome:

- If Δ yaw > 0: re-implement `PRE_GRASP_ORIENT` and `REORIENT` using quaternion
  targets.
- If Δ yaw ≈ 0: controller does not support explicit orientation control; must
  switch embodiment or approach.

### 6.2 Multi-seed v3 ablation

Run v3 policy with multiple seeds and report mean/max hold duration.

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
for seed in 0 1 2 3 4; do
  python scripts/diagnostics/run_goal_pose_trace.py \
    --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
    --seed $seed
done
```

### 6.3 Gripper force / closure ablation

Test different `gripper_close_threshold` and squeeze-step counts to map the
grasp-stability frontier.

### 6.4 Joint-space feasibility check

Try switching to `franka_joint_pos` for a few episodes to see if orientation
control becomes available.

---

## 7. Recommended Next Actions

| Order | Action | Rationale |
|---|---|---|
| 1 | Send this issue tracker to the Arena team | The P0 controller question blocks all orientation-dependent progress. |
| 2 | Run absolute quaternion calibration | Inexpensive; directly tests the most likely workaround. |
| 3 | Run 5-seed v3 ablation | Quantifies variance of the v3 hold-duration improvement. |
| 4 | Test `franka_joint_pos` orientation control | Determines whether the issue is specific to `franka_ik`. |
| 5 | Tune gripper force/friction if yaw is fixed | Long hold instability remains after yaw is resolved. |

---

## 8. Honest Claim Boundary

Until the P0 controller/action-space question is answered:

- **Do not claim** `goal_pose` is solved.
- **Do not claim** cross-task transfer of grasp-stability hints is validated.
- **Can claim** rigorous physical diagnosis, reproducible traces, and a v3
  intervention that extends hold duration ~9× without relying on broken yaw
  control.

---

## Source Reports

- `reports/ROTATIONAL_ACTION_CALIBRATION_REPORT.md`
- `reports/GOAL_POSE_DIAGNOSTIC_REPORT_FOR_EXTERNAL_REVIEW.md`
- `reports/EXTERNAL_GOAL_POSE_REVIEW_PACKAGE_REPORT.md`
- `reports/POLICY_V3_INTERVENTION_REPORT.md`
- `reports/FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md`
- `reports/GRIPPER_CALIBRATION_REPORT.md`
- `reports/GOAL_POSE_PHYSICS_ABLATION_REPORT.md`
- `external_reviews/goal_pose_diagnosis_pack/questions_for_arena_team.md`
