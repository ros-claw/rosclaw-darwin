# Pre-Grasp Yaw Alignment v2 Report

**Date:** 2026-06-19

**Goal:** Reduce large-yaw in-hand slip by aligning the gripper yaw **before** grasping, so that the post-grasp reorientation is only a small residual rotation.

---

## 1. Context

In v1.5 the `target_yaw_override` diagnostic showed that large target yaws (especially π/2) caused the cube to rotate inside the gripper while the gripper tracked the desired yaw (`reports/POLICY_V3_INTERVENTION_REPORT.md`, section 10):

| target_yaw (rad) | lifted_rate | orientation_achieved_rate | env_success_rate |
|---|---:|---:|---:|
| 0.0000 | 0.90 | 0.90 | 0.90 |
| 0.5236 | 0.90 | 0.20 | 0.90 |
| 0.7854 | 0.90 | 0.20 | 0.90 |
| 1.0472 | 0.80 | 0.20 | 0.80 |
| 1.5708 | 0.30 | 0.10 | 0.30 |

The post-GRASP-pose-hold fix improved grasp reliability, but large reorientations still slipped because the fingers had to rotate the cube by a large angle while maintaining contact.

Pre-grasp yaw alignment v2 attempts to remove most of that in-hand rotation by:

1. Aligning the gripper yaw to the target yaw **while still above the object**.
2. Grasping in that aligned orientation.
3. Performing only a small residual reorientation after LIFT.

---

## 2. Implementation

Files:

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `configs/policies/heuristic_servo_goal_pose_v3_yaw_align.yaml`

Policy parameters added:

```yaml
pre_grasp_yaw_align_v2: true
pre_grasp_yaw_strategy: "target_yaw_before_grasp"
pre_grasp_yaw_fraction: 0.8
pre_grasp_yaw_max_step: 0.2
pre_grasp_yaw_settle_steps: 3
post_grasp_yaw_residual_fraction: 0.2
```

State-machine additions:

- `PRE_GRASP_YAW_ALIGN` phase: the gripper stays above the object (`object_pos + approach_offset_z`) and rotates its yaw toward `object_yaw + grasp_target_yaw_offset`. Once the yaw error is below `pre_grasp_yaw_threshold` (or safety/timeout), it transitions to `DESCEND`.
- `REORIENT` phase: if v2 is enabled, only the residual fraction (`post_grasp_yaw_residual_fraction`) of the full yaw change is applied after LIFT, reducing the in-hand rotation torque.

---

## 3. Validation status

The v1.6 100-seed official `dex_cube` validation (`reports/DEX_CUBE_GOAL_POSE_100_SEED_VALIDATION_REPORT.md`) fixed the environment's target yaw to π/2 for all seeds and reported:

- `orientation_achieved_rate = 1.0`
- 17/18 failures were `approach_collision`, not in-hand slip.

This means **large-yaw in-hand slip is not the current dominant bottleneck** on the official asset. The primary limit is the positive-y / positive-yaw approach collision addressed by the reachability-aware planner.

Consequently, the pre-grasp yaw-alignment v2 ablation was deprioritized behind the reachability work. The code and config are in place; a full target-yaw sweep with/without v2 remains as follow-up if the external experts want to push the π/2 reorientation ceiling further.

---

## 4. Honest conclusion

1. Pre-grasp yaw alignment v2 is implemented and non-regressive (single-seed smoke tests pass).
2. On the current official `dex_cube` 100-seed distribution, orientation achievement is already 100%, so the expected gain from this intervention is small.
3. The intervention is most relevant for **future tasks with variable or larger target yaws**, where in-hand reorientation torque would again become the bottleneck.
4. Next step: run a controlled `target_yaw_override` matrix (`0, π/6, π/4, π/3, π/2`) with `heuristic_servo_goal_pose_v3.yaml` vs `heuristic_servo_goal_pose_v3_yaw_align.yaml` to quantify the v2 effect when the target-yaw distribution is intentionally widened.

---

## 5. Files changed

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `configs/policies/heuristic_servo_goal_pose_v3_yaw_align.yaml`
- `reports/PRE_GRASP_YAW_ALIGNMENT_V2_REPORT.md` (this report)
