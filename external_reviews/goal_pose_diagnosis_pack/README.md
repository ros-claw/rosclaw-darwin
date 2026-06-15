# ROSClaw-Darwin Goal Pose Diagnosis Package

This package contains the physical-diagnosis evidence for the `goal_pose`
bottleneck in IsaacLab-Arena Docker.

## Contents

| file | description |
|---|---|
| `GOAL_POSE_TRACE_SCHEMA_V2_REPORT.md` | Separates object yaw error from end-effector yaw error. |
| `GRIPPER_CALIBRATION_REPORT.md` | Empty vs. cube-blocked gripper closure limits. |
| `ROTATIONAL_ACTION_CALIBRATION_REPORT.md` | Mapping of `action[..., 3:6]` to eef rotation. |
| `GOAL_POSE_GRASP_STABILITY_METRICS_V3_REPORT.md` | Object-following stability analysis. |
| `GOAL_POSE_PHYSICS_ABLATION_REPORT.md` | Friction / size / mass diagnostic ablations. |
| `GOAL_POSE_SUBTASK_DECOMPOSITION_REPORT.md` | Lift-only, lift-hold, yaw subtask boundary. |
| `FAILURE_SIGNATURE_V3_HINT_RECIPE_REPORT.md` | New signature tags and recipes. |
| `CROSS_TASK_TRANSFER_STATUS_V2_REPORT.md` | Transfer level refresh. |
| `sample_traces/goal_pose_trace_v2_episode_0.jsonl` | 2500-step per-step trace. |
| `sample_traces/subtask_decomposition_*.json` | Subtask results. |
| `sample_traces/physics_ablation_*.json` | Physics ablation results. |
| `questions_for_arena_team.md` | Specific questions for IsaacLab-Arena experts. |

## One-line summary

ROSClaw-Darwin can lift and hold the procedural cube, but it cannot actively
reorient it because the `franka_ik` relative-mode rotational action has no
measurable authority over end-effector yaw.

## Branch

Code is on `arena-episode-eval-fix` in the `rosclaw-darwin` repository.
