# Learned Policy Baseline Integration Report

## 1. Goal

Provide a learned-policy comparison baseline for Darwin's heuristic + hint
pipeline, **without blocking the main evaluation line**.  The learned baseline
is treated as a separate branch: if it works, we compare; if it does not, we
document why and keep the heuristic pipeline as the primary evidence source.

## 2. Existing integration

- Policy configs:
  - `configs/policies/rsl_rl_lift_object.yaml`
  - `configs/policies/rsl_rl_lift_object_joint_pos.yaml`
  - `configs/policies/rsl_rl_lift_object_official.yaml`
- `ArenaAdapter` already maps ``type: rsl_rl`` to
  ``isaaclab_arena.policy.rsl_rl_action_policy.RslRlActionPolicy``.
- `LEARNED_LIFT_BASELINE_REPORT.md` documents a prior attempt: both checkpoints
  returned ``success_rate = 0.0`` because of checkpoint / observation-space /
  embodiment mismatches.

## 3. Proposed comparison matrix

| Condition | Purpose |
|---|---|
| `zero_action` | Sanity: does the env ever succeed by chance? |
| `heuristic_servo_lift` | Darwin main-line policy |
| `heuristic_servo_lift + auto hints` | Darwin main-line with failure-to-hint |
| `rsl_rl_lift_object` | Learned baseline |
| `rsl_rl_lift_object + auto hints` | Can Darwin hints help a learned policy? |

## 4. Blockers and resolution plan

| Blocker | Impact | Next step |
|---|---|---|
| Checkpoint / obs-space mismatch | Learned policy produces no useful action | Verify checkpoint config matches current Arena obs terms, or re-train a small RSL-RL policy in the current container |
| Embodiment mismatch | Joint-pos checkpoint vs IK embodiment | Run joint-pos embodiment if possible, or re-train on IK embodiment |
| Training time | Full RSL-RL training is hours/days | Keep as background effort; do not gate heuristic-pipeline reports |

## 5. Honest conclusion

Learned-policy baseline integration is **wired at the config / adapter level**,
but no validated checkpoint currently produces non-zero success.  The main
Darwin evidence line therefore remains the heuristic servo policy and the
failure-to-hint ablations.  Once a compatible checkpoint is available, the
comparison matrix above can be executed with the same ablation scripts.

## 6. Next step

Resolve the RSL-RL checkpoint mismatch (see `LEARNED_LIFT_BASELINE_REPORT.md`)
or generate a new checkpoint directly in the current Arena Docker environment.
Until then, learned baseline is documented but not claimed as evidence.
