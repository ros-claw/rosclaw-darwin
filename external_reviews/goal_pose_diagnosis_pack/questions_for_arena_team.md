# Questions for IsaacLab-Arena Team / Simulation Experts

## Controller / action space

1. For `franka_ik` with `DifferentialInverseKinematicsActionCfg(command_type="pose", use_relative_mode=True)`,
   what is the exact semantic of `action[..., 3:6]`?
   - Is it a quaternion delta, rotation vector, Euler-angle delta, or something else?
2. Our calibration shows that commanding pure values on `action[..., 3]`, `action[..., 4]`,
   and `action[..., 5]` produces zero change in end-effector roll/pitch/yaw.
   Is this expected for the default `franka_ik` embodiment?
3. What is the recommended way to command end-effector yaw reorientation in this setup?
   - Should we set `action[..., 3:7]` to a target quaternion?
   - Should we use `use_relative_mode=False` and supply absolute pose?
   - Should we use a different embodiment such as `franka_joint_pos`?

## Gripper / object

4. The official `dex_cube` is not available in our Docker runtime, so we fall back to
   `procedural_cube` with size `(0.05, 0.1, 0.1)` m and mass `0.2` kg.
   Is this consistent with the intended `dex_cube`?
5. With the cube held, `gripper_pos` (mean of last two finger joints) bottoms at ~0.024.
   Is this the expected joint value when the fingers are blocked by the cube?
6. Is there a recommended grasp-success proxy other than `gripper_pos < threshold`?

## Task / success

7. Does `GoalPoseTask` in `cube_goal_pose` terminate early only on object height + yaw,
   or does it also require the object to be stationary?
8. Is there an official teleop, heuristic, or learned policy that can solve
   `cube_goal_pose` with `franka_ik`?

## Physics

9. If the cube slips inside the gripper during reorientation, which parameters should
   we tune first: gripper force limit, finger friction, object friction, or solver iterations?
10. Can we change the procedural cube's physics material/size/mass at runtime for
    diagnostic ablations, or should we register a new asset variant?
