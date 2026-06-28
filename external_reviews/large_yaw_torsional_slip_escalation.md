# Large-Yaw Torsional Slip — Arena Escalation Package

**Prepared:** 2026-06-21
**Status:** Ready to submit / attach to IsaacLab-Arena issue
**Related tracker:** `reports/ARENA_ISSUE_TRACKER.md` §5
**Blocking claim:** Large-yaw orientation achievement for `cube_goal_pose` with `franka_ik_abs`.

---

## 1. Executive Summary

With the official `dex_cube` asset and the `franka_ik_abs` absolute-pose
embodiment, the current policy lifts the object reliably but cannot orient it to
large target yaws (π/2 and 2π/3). A systematic diagnostic and four targeted
open-loop structural interventions all fail to improve
`orientation_achieved_rate` by ≥20% relative. The binding failure mode is
**torsional slip inside the pinch grasp**: the object rotates relative to the
gripper while the gripper is commanded to the target yaw.

We believe this is beyond the current open-loop position-control policy space
and requires Arena-side contact/gripper engineering or closed-loop force/tactile
feedback. We are holding all large-yaw orientation claims until the physics or
sensor surface is clarified.

---

## 2. Evidence

### 2.1 Large-yaw slip diagnosis

Script: `scripts/diagnostics/run_large_yaw_slip_diagnosis.py`

Report: `reports/LARGE_YAW_SLIP_MECHANISM_REPORT.md`

| Target Yaw | Lifted Rate | Orient Achieved | Dominant Category |
|---|---:|---:|---:|
| π/2 (1.5708) | 100% | 10% | `torsional_slip` 9, `eef_yaw_failure` 9, `success` 2 |
| 2π/3 (2.0944) | 100% | 0% | `torsional_slip` 18, `eef_yaw_failure` 2 |

The object is lifted in every run. The failure is orientation, not pick-up.

### 2.2 Targeted intervention ablation

Script: `scripts/ablations/run_large_yaw_intervention_ablation.py`

Artifact: `data_v17/ablations/large_yaw_intervention/aggregate_summary.json`

Report: `reports/LARGE_YAW_TARGETED_INTERVENTION_REPORT.md`

| Condition | Target Yaw | Orient Achieved | EEF Yaw Failure | Torsional Slip |
|---|---:|---:|---:|---:|
| baseline | π/2 | 0.10 (2/20) | 9 | 9 |
| baseline | 2π/3 | 0.00 (0/20) | 2 | 18 |
| grasp_at_target_yaw | π/2 | 0.10 (2/20) | 0 | 18 |
| grasp_at_target_yaw | 2π/3 | 0.05 (1/20) | 1 | 18 |
| low_height_incremental_yaw | π/2 | 0.05 (1/20) | 2 | 17 |
| low_height_incremental_yaw | 2π/3 | 0.00 (0/20) | 16 | 4 |
| table_push_align | π/2 | 0.10 (2/20) | 1 | 17 |
| table_push_align | 2π/3 | 0.00 (0/20) | 0 | 20 |
| table_push_align_tuned | π/2 | 0.10 (2/20) | 0 | 18 |
| table_push_align_tuned | 2π/3 | 0.00 (0/20) | 1 | 19 |

Interventions that improve pre-grasp yaw authority (`grasp_at_target_yaw`,
`table_push_align`) eliminate most `eef_yaw_failure` but convert those failures
into `torsional_slip` without improving net `orientation_achieved_rate`. The
tuned push-align variant (more time, higher z-offset, faster yaw step, stronger
lateral oscillation, reduced downward pressure) produced the same outcome.

### 2.3 What the failure looks like

- The gripper reaches the target yaw (or close to it).
- The object follows initially, then twists back relative to the gripper.
- Final object yaw error is well outside the 0.5 rad diagnostic threshold
  (mean ≈ 1.4–1.6 rad at π/2, larger at 2π/3).
- `gripper_pos` stays at the blocked-close value (~0.024), so the gripper does
  not visibly open; the slip is torsional inside the pinch.

---

## 3. Reproduction

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

# Diagnosis
python scripts/diagnostics/run_large_yaw_slip_diagnosis.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --target-yaws 1.5708 2.0944 \
  --seeds 0:19 \
  --out-dir data_v17/diagnostics/large_yaw_slip \
  --cleanup

# Intervention ablation
python scripts/ablations/run_large_yaw_intervention_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --target-yaws 1.5708 2.0944 \
  --seeds 0:19 \
  --conditions baseline,grasp_at_target_yaw,low_height_incremental_yaw,table_push_align,table_push_align_tuned \
  --out-dir data_v17/ablations/large_yaw_intervention \
  --cleanup
```

Expected outcome: near-perfect lift, near-zero orientation achievement at
2π/3, and no intervention improving orientation achievement by ≥20% relative.

---

## 4. Request to the Arena Team

1. **Confirm** whether large-yaw torsional slip is expected for the default
   `dex_cube` + Franka gripper contact properties, or whether the gripper/object
   parameters should allow stable 2π/3 in-hand orientation.
2. **Provide** the default gripper finger friction coefficient, maximum closure
   force, and object friction/restitution values for `dex_cube`.
3. **Clarify** whether the gripper force limit or finger friction can be
   increased via task config or environment argument.
4. **Document** any contact sensors, finger force/torque, or tactile feedback
   exposed by `cube_goal_pose` / `franka_ik_abs` that could be used for slip
   detection and recovery.
5. **Recommend** the intended way to perform compliant push-align against the
   table (exploiting table reaction torque) without explicit force feedback.
6. **State** whether the target yaw tolerance (`orientation_threshold`) or
   success metric should be relaxed for large-yaw evaluation, or whether the
   task is intended to require precise large-yaw orientation.

---

## 5. Local Claim Boundary

Until the Arena team clarifies or fixes the contact/gripper surface:

- **Do not claim** that `cube_goal_pose` is solved for large target yaws.
- **Do not claim** cross-yaw generalization beyond the small-yaw regime where
  torsional slip is not observed.
- **Can report** the diagnosis, the rejected interventions, and the honest
  conclusion that the current open-loop position-control policy cannot solve
  large-yaw orientation without Arena-side changes or force/tactile feedback.

---

## 6. Draft GitHub Comment / Issue Text

Below is a ready-to-post comment for a new or existing Arena issue.

```markdown
## Large-yaw in-hand torsional slip cannot be fixed by open-loop policy interventions

We diagnosed large-yaw orientation failures on `cube_goal_pose` with the official
`dex_cube` asset and `franka_ik_abs` embodiment.

**Result:** the object lifts reliably (100%) but orientation achievement is near
zero at π/2 (10%) and 2π/3 (0%). The dominant failure mode is torsional slip
inside the pinch grasp.

We tested four open-loop structural interventions:
- `grasp_at_target_yaw` — align gripper to target yaw before descending.
- `low_height_incremental_yaw` — small lift height, incremental yaw alignment.
- `table_push_align` — press object against table while applying yaw torque.
- `table_push_align_tuned` — longer push-align, higher z-offset, faster yaw step,
  stronger lateral oscillation, reduced downward pressure.

None improved `orientation_achieved_rate` by ≥20% relative. Interventions that
fix pre-grasp yaw authority convert `eef_yaw_failure` into `torsional_slip`
without improving net success.

**Reproduction:**
```bash
python scripts/ablations/run_large_yaw_intervention_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --target-yaws 1.5708 2.0944 \
  --seeds 0:19 \
  --conditions baseline,grasp_at_target_yaw,low_height_incremental_yaw,table_push_align,table_push_align_tuned \
  --out-dir data_v17/ablations/large_yaw_intervention \
  --cleanup
```

**Ask:**
1. Is large-yaw torsional slip expected for the default `dex_cube` + Franka gripper?
2. What are the default finger/object friction and gripper force limit?
3. Can gripper force or finger friction be increased via config/argument?
4. Are contact sensors or finger force/torque available for slip detection?
5. What is the recommended way to use table reaction torque for yaw alignment?
6. Should the large-yaw success tolerance be relaxed, or is precise orientation required?

We are blocking all large-yaw success claims until the contact/gripper surface is clarified.
```

---

## 7. Files Referenced

- `scripts/diagnostics/run_large_yaw_slip_diagnosis.py`
- `scripts/ablations/run_large_yaw_intervention_ablation.py`
- `scripts/ablations/merge_large_yaw_intervention_aggregates.py`
- `data_v17/diagnostics/large_yaw_slip/aggregate_summary.json`
- `data_v17/ablations/large_yaw_intervention/aggregate_summary.json`
- `reports/LARGE_YAW_SLIP_MECHANISM_REPORT.md`
- `reports/LARGE_YAW_TARGETED_INTERVENTION_REPORT.md`
- `reports/ARENA_ISSUE_TRACKER.md`
- `reports/FINAL_DARWIN_V17_STATUS_REPORT.md`
