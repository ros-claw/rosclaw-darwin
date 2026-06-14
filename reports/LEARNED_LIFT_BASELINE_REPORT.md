# Learned Lift Baseline Report

## Goal

Run pretrained RSL-RL policies on the real Arena `lift_object` task to
determine whether a learned controller can produce non-zero success/progress
where the damped DifferentialIK servo heuristic currently fails.

## Method

- Task: `darwin_mvp_03_lift_object` (Arena Docker, `franka_ik` embodiment).
- Policies: pretrained RSL-RL checkpoints mounted into the Arena container.
- Metrics: success_rate, progress_mean, min eef-to-object distance, object height delta.
- Failure types are inferred from per-episode traces.

## Results

| Policy | Checkpoint | Status | success_rate | progress_mean | min_dist_mean | height_delta_mean |
|--------|------------|--------|-------------:|--------------:|--------------:|------------------:|
| rsl_rl_lift_object_rsl_rl | `/workspace/isaaclab_arena/logs/rsl_rl/lift_object_rsl_rl/2026-06-07_14-35-00_run_001/model_999.pt` | completed | 0.0000 | 0.0000 | n/a | n/a |
| rsl_rl_lift_object_joint_pos | `/workspace/isaaclab_arena/logs/rsl_rl/lift_object_joint_pos/2026-06-09_00-39-14/model_13400.pt` | failed | 0.0000 | 0.0000 | n/a | n/a |

## Failure-type breakdown

### rsl_rl_lift_object_rsl_rl
- No failure-type metadata captured.

### rsl_rl_lift_object_joint_pos
- No failure-type metadata captured.

## Conclusion

No learned checkpoint produced non-zero success on `lift_object` in this run. Possible reasons: checkpoint/observation-space mismatch, embodiment mismatch, or the checkpoint was trained in a different environment variant. The next step is to verify checkpoint compatibility or train/fine-tune a policy directly in the current Arena container configuration.

## Honest claim status

- These policies are **not** oracle/cheat; they can claim real capability if success > 0.
- Evolution evidence still requires a measurable improvement after consuming auto skill hints.
