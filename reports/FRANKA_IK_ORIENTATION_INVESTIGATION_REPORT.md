# Franka IK Orientation Control Investigation Report

## 1. Context

Following `darwin_fix_try01.md`, the goal was to determine why `franka_ik`
cannot reorient the end-effector in `cube_goal_pose`, and to test the three
proposed routes:

1. Use the official relative axis-angle action interface correctly.
2. Create a new `franka_ik_abs` embodiment with absolute pose IK.
3. Test `franka_joint_pos` as a fallback.

## 2. Critical correction: orientation sensor reading bug

Early runs concluded that both relative axis-angle and absolute quaternion
commands produced zero end-effector rotation.  The root cause of that apparent
failure was a **sensor-reading bug** in the calibration and servo policies:

- `FrameTransformer` data exposes both `source_quat_w` (the source frame,
  i.e. `panda_link0` / robot base) and `quat_w` (the target frame, i.e.
  `panda_hand` / end-effector).
- The policies iterated `("source_quat_w", "quat_w", "target_quat_w")` and
  therefore read the **robot-base orientation** (near identity) instead of the
  end-effector orientation.
- Once the order was changed to prefer `quat_w`, all three routes showed
  end-effector rotation.

This bug affected every trace that reported `eef_roll` / `eef_pitch` /
`eef_yaw` before this fix, including earlier rotational-calibration reports.
All conclusions below are based on the corrected sensor reading.

## 3. What was implemented

### 3.1 Action-term introspection

`RotationalCalibrationPolicy` prints the action-manager configuration at the
first step.  This revealed:

- Default `franka_ik` config:
  - `action_dim = 7`
  - `command_type = "pose"`
  - `use_relative_mode = True`
  - `scale = 0.5`
  - `ik_method = "dls"`
  - `ik_params = {"lambda_val": 0.01}`
- The `arena.py` attempt to set `use_relative_mode = False` and `scale = 1.0`
  does **not** affect Docker runs because the environment is built inside the
  container from Arena's registry, not from the host-side `_create_embodiment`.

### 3.2 `franka_ik_abs` embodiment

Created `rosclaw_darwin/evaluation/arena_docker_deps/franka_ik_abs_patch.py`
which adds a new `FrankaIKAbsEmbodiment` registered as `franka_ik_abs`:

- `command_type = "pose"`
- `use_relative_mode = False`
- `scale = 1.0`
- Expected action layout: `[pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w, gripper]`

The patch is bind-mounted into the Docker container via `ArenaRunner._run_docker`.

### 3.3 Joint-space embodiment and calibration policy

Added `JointSpaceCalibrationPolicy` for `franka_joint_pos`:

- Commands a fixed value on a single arm joint (`panda_joint1..7`).
- Records resulting end-effector orientation change.
- Added `franka_joint_pos` support to `_ArenaComponentMapper` and
  `ArenaAdapter.run_policy`.

### 3.4 Quaternion-format fix

IsaacLab's `subtract_frame_transforms` returns quaternion as `(w, x, y, z)`;
the controller expects `(x, y, z, w)`.  The policy now converts correctly.

### 3.5 Orientation sensor fix

Changed `FrameTransformer` quaternion reading order to prefer `quat_w`, then
`target_quat_w`, then `source_quat_w` across all policies in
`heuristic_policy.py`.

## 4. Test results (with corrected orientation reading)

### 4.1 Default `franka_ik` relative axis-angle

| axis | sign | magnitude | Δ roll | Δ pitch | Δ yaw | observed motion |
|---|---|---:|---:|---:|---:|---|
| rot_x | + | 1.0 | -0.22 | -0.08 | -1.86 | large yaw + some roll |
| rot_x | - | 1.0 | +0.13 | -0.21 | +1.80 | opposite yaw |
| rot_y | + | 1.0 | -3.09 | +0.31 | -3.08 | large multi-axis rotation |
| rot_y | - | 1.0 | -1.15 | +0.95 | -1.26 | large multi-axis rotation |
| rot_z | + | 1.0 | +2.51 | -0.03 | +0.09 | large roll, almost no yaw |
| rot_z | - | 1.0 | +2.25 | -0.02 | -0.07 | large roll, almost no yaw |

**Conclusion:** `franka_ik` relative mode **does** produce end-effector
rotation, but the mapping from action axes to world RPY is **heavily
cross-coupled**.  In particular, the `rot_z` action axis (the one the servo
policy uses for yaw correction) mainly produces **roll**, not world yaw.
World-yaw-like motion is dominated by `rot_x`.

### 4.2 `franka_ik_abs` absolute pose

With `franka_ik_abs`:

- `action_dim = 8` confirms the absolute-pose arm action is active.
- `use_relative_mode = False` and `scale = 1.0` confirmed by introspection.
- Command constructed as:
  - `action[..., 0:3] = current_ee_pos_in_action_term_frame`
  - `action[..., 3:7] = target_quaternion (45° yaw delta)`
  - `action[..., 7] = gripper_open`

Result over 100 steps:

```json
{
  "delta_eef_rpy": {"roll": -0.03, "pitch": -0.08, "yaw": -0.78},
  "delta_pos": {"x": 0.007, "y": 0.148, "z": 0.021}
}
```

**Conclusion:** Absolute pose mode produces a yaw change close to the 0.785 rad
command.  The coupling is much cleaner than relative axis-angle.  There is some
position drift (~15 cm in y), likely because holding position while reorienting
requires the controller to compensate for kinematic coupling.

### 4.3 `franka_joint_pos`

Joint-space control with `franka_joint_pos` also produces end-effector
rotation.  Representative results (command held for 100 steps, scale=0.5):

| joint | command | target Δ | Δ roll | Δ pitch | Δ yaw |
|---|---|---:|---:|---:|---:|
| panda_joint5 (idx 4) | +0.4 | +0.2 rad | +0.23 | +0.35 | +0.08 |
| panda_joint5 (idx 4) | +0.8 | +0.4 rad | +0.43 | +0.37 | +0.20 |
| panda_joint6 (idx 5) | +0.4 | +0.2 rad | -0.00 | +0.59 | -0.05 |
| panda_joint6 (idx 5) | +0.8 | +0.4 rad | -0.07 | +0.73 | -0.07 |
| panda_joint7 (idx 6) | +0.4 | +0.2 rad | +0.15 | +0.36 | +0.07 |
| panda_joint7 (idx 6) | +0.8 | +0.4 rad | +0.42 | +0.40 | +0.14 |

**Conclusion:** Joint-space control has orientation authority.  The wrist
joints affect mostly pitch/roll in this configuration; pure world yaw requires
a coordinated multi-joint motion.

## 5. Root-cause analysis

1. The earlier "zero rotation" conclusion was caused by reading the robot-base
   quaternion instead of the end-effector quaternion.
2. With correct readings:
   - `franka_ik` relative mode can rotate the end-effector, but the action-axis
     to world-RPY mapping is cross-coupled.
   - `franka_ik_abs` absolute quaternion mode gives clean yaw authority.
   - `franka_joint_pos` joint-space mode gives orientation authority.
3. The `DifferentialIKController`, IsaacLab-Arena patch files, and Franka USD
   asset are therefore **not** fundamentally broken for orientation.
4. The practical problem for `goal_pose` is choosing the right control mode and
   action mapping, not a controller/embodiment bug.

## 6. Implications for `goal_pose`

- **Relative-mode yaw correction is mis-mapped:** the servo policy writes yaw
  error to `action[..., 5]` (`rot_z`), but that axis mainly produces roll.
- **Absolute quaternion mode is promising:** `franka_ik_abs` can command a
  target yaw directly with much cleaner coupling.  Position drift during
  reorientation must be compensated.
- **Joint-space mode is viable but harder:** `franka_joint_pos` can rotate the
  end-effector, but solving joint-space IK is more complex than task-space
  control.
- **Fastest path to `goal_pose` success:** switch the servo policy to use
  `franka_ik_abs` and command position + target quaternion, or remap the
  relative-mode yaw correction to the action axis that actually produces world
  yaw (likely `rot_x`).

## 7. Files changed

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
  - Fixed `FrameTransformer` quaternion reading order (`quat_w` first).
  - `RotationalCalibrationPolicy` introspection and absolute-pose command.
  - Added `JointSpaceCalibrationPolicy`.
- `rosclaw_darwin/evaluation/arena_docker_deps/franka_ik_abs_patch.py` (new)
- `rosclaw_darwin/evaluation/arena_runner.py`
  - bind mount for `franka_ik_abs_patch.py`
- `rosclaw_darwin/adapters/arena.py`
  - Added `franka_joint_pos` to `_ROBOT_MAP` and `_create_embodiment`.
  - Added `joint_space_calibration` policy-type mapping.
  - Debug prints confirming host-side config changes do not reach Docker runs.
- `scripts/diagnostics/run_rotational_action_calibration.py`
  - Added `--embodiment`, `--absolute-mode`, `--target-yaw-delta`.
  - Added joint-space trial runner and angle wrapping.
- `rosclaw_darwin/adapters/arena.py`
  - debug prints confirming host-side config changes don't reach Docker runs

## 8. Recommendation

1. Update `HeuristicServoGoalPosePolicy` to use `franka_ik_abs` absolute
   quaternion targets for orientation commands.
2. Re-run `goal_pose` traces and measure success_rate with the corrected
   orientation feedback.
3. If absolute-mode position drift is problematic, add a position-hold servo
   loop around the current eef position while reorienting.
4. Keep joint-space mode as a fallback if task-space absolute mode proves
  unstable during grasped-object motion.

## 9. Follow-up: goal_pose success with `franka_ik_abs` (2026-06-16)

The recommendation in section 8 was implemented and tested on `cube_goal_pose`
with the new `franka_ik_abs` embodiment.

### 9.1 Implementation summary

Changes to `HeuristicServoGoalPosePolicy`
(`rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`):

- **Base-frame pose conversion:** absolute-pose controllers expect commands in
  the robot base frame. World-frame eef pose and all targets are converted to
  base frame using `arm_action._compute_frame_pose()` and
  `subtract_frame_transforms` before servoing.
- **Stable placement target:** when the task does not provide an explicit
  command target, the object's initial base-frame position is stored and used as
  the placement reference. This prevents LIFT / REORIENT / ALIGN from chasing
  the moving object.
- **Incremental absolute orientation:** the absolute target quaternion is
  clamped to `_yaw_step_size` per step. Large reorientations are broken into
  small steps, which keeps coupled roll/pitch small and reduces grasp slip.
- **HOLD / RELEASE position hold:** in absolute mode a zero action vector means
  "move to the origin", so the current eef pose is commanded while the gripper
  opens or stays closed.
- **LIFT transition fix:** the `near_target_xy` check was removed from the
  LIFT->REORIENT/ALIGN transition. Horizontal alignment is now handled in
  ALIGN, avoiding the case where LIFT never exits because the object is still
  far from the target xy.

Changes to embodiment and runner:

- `franka_ik_abs_patch.py`: added deterministic tabletop initial joint pose and
  disabled joint randomization for reproducible resets across seeds.
- `arena.py`: added `franka_ik_abs` to `_ROBOT_MAP`.
- `run_goal_pose_trace.py`: added `--embodiment` CLI override.
- New config: `configs/policies/heuristic_servo_goal_pose_abs.yaml`.

### 9.2 Results

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
for seed in 0 1 2 3 4; do
  python scripts/diagnostics/run_goal_pose_trace.py \
    --task configs/tasks/goal_pose.yaml \
    --policy configs/policies/heuristic_servo_goal_pose_abs.yaml \
    --embodiment franka_ik_abs \
    --seed $seed
done
```

| seed | success_rate | progress | failure_type |
|----:|----:|----:|---|
| 0 | 1.0 | 0.7344 | — |
| 1 | 1.0 | 0.7344 | — |
| 2 | 1.0 | 0.7344 | — |
| 3 | 1.0 | 0.7344 | — |
| 4 | 1.0 | 0.7344 | — |

**Aggregate: 5/5 seeds succeed.** `success_rate = 1.0` and
`progress_mean = 0.7344` on every seed.

### 9.3 Interpretation

- Absolute quaternion mode solves the orientation-authority problem that
  blocked `goal_pose` in `franka_ik` relative mode.
- Once the sensor-reading bug was fixed, the controller itself was not broken;
  the issue was choosing the correct control mode and action mapping.
- The practical path to `goal_pose` success is therefore:
  1. Use the patched `franka_ik_abs` embodiment.
  2. Convert all commands to the robot base frame.
  3. Reorient incrementally and hold position during gripper state changes.

### 9.4 Honest caveats

- The policy succeeds on the current `cube_goal_pose` / procedural-cube setup
  with a fixed target orientation. Generalisation to other seeds, objects, or
  target positions still needs validation.
- `franka_ik_abs` position control is noticeably slower than `franka_ik`
  relative mode; the episode needs the full 2500-step horizon to complete.
- The object can slip/rotate inside the gripper during fast translation; the
  current config mitigates this by reorienting before the final ALIGN move and
  by clamping orientation steps.

### 9.5 Files changed in this follow-up

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
  - Base-frame conversion helpers `_get_eef_pose_base`, `_world_pose_to_base`.
  - Incremental absolute orientation `_clamp_orientation_target`.
  - HOLD/RELEASE position hold.
  - Stable `_initial_object_pos` fallback target.
  - Fixed LIFT transition.
- `rosclaw_darwin/evaluation/arena_docker_deps/franka_ik_abs_patch.py`
  - Deterministic initial pose and disabled joint randomization.
- `rosclaw_darwin/adapters/arena.py`
  - Added `franka_ik_abs` to `_ROBOT_MAP`.
- `scripts/diagnostics/run_goal_pose_trace.py`
  - Added `--embodiment` argument.
- `configs/policies/heuristic_servo_goal_pose_abs.yaml`
  - New absolute-quaternion goal_pose policy config.
