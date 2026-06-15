# External Goal Pose Review Package Report

## 1. What is in the package

The package at `external_reviews/goal_pose_diagnosis_pack/` contains:

- All physical-diagnosis reports (trace schema v2, gripper calibration,
  rotational calibration, grasp stability v3, physics ablation, subtask
  decomposition, FailureSignature v3, cross-task transfer v2).
- A 2500-step sample trace (`sample_traces/goal_pose_trace_v2_episode_0.jsonl`).
- JSON summaries for subtask decomposition and physics ablation.
- `questions_for_arena_team.md` with 10 specific questions.

## 2. Key findings

1. **Gripper closure is not the bottleneck.** Empty close reaches ~0.00012;
   cube-blocked close stops at ~0.024 with a moderate command, which is
   geometrically normal.
2. **Rotational action has zero authority.** Commanding `action[..., 3:6]`
   produces no measurable change in end-effector roll/pitch/yaw.
3. **Object follows eef but slips during reorientation.** Mean object-eef
   distance is ~5 mm; the cube is lifted to ~0.33 m but then drops while
   passively rotating inside the gripper.
4. **First failing subtask is reorientation / yaw alignment.** Lift-only and
   lift-hold succeed; any yaw requirement fails.
5. **Physics ablation does not solve the problem.** High friction, smaller
   cube, and lighter cube all lift but none achieve target yaw.

## 3. What we need from external experts

- Confirmation of how `franka_ik` action space maps to end-effector rotation.
- Recommended controller configuration or embodiment to enable yaw control.
- Clarification on whether fallback `procedural_cube` matches the intended
  `dex_cube`.
- Recommended grasp-success proxy and gripper force/friction tuning.

## 4. How to use the package

Send the entire `external_reviews/goal_pose_diagnosis_pack/` directory to
IsaacLab-Arena maintainers or simulation experts.  The trace file can be
analyzed with standard JSONL tools.

## 5. Honest claim status

We can claim a rigorous physical diagnosis.  We cannot claim `goal_pose` is
solved until a working yaw-control path is found.
