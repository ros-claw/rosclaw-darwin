# ROSClaw-Darwin v1.7 Milestone and External Escalation Report

**Date:** 2026-06-21
**Status:** v1.7 milestone frozen; two external escalation packages finalized and ready for submission pending user approval.

---

## 1. v1.7 milestone summary

See `reports/MILESTONE_DARWIN_V17_OFFICIAL_GOALPOSE_BREAKTHROUGH.md` for the full frozen milestone.

Key facts:

| Item | Value |
|---|---|
| Official benchmark | `goal_pose + dex_cube + franka_ik_abs + reachability-promoted v3` |
| Success rate | **99/100 (99.0%)** |
| Wilson 95% CI | [94.55%, 99.82%] |
| Asset fallback | 0 |
| Physics anomaly | 0 |
| Approach collision | 0 |
| Remaining failure | seed 24 post-lift slip |
| Procedural OOD | invalid environment (collision/bbox) |
| Large-yaw | torsional slip dominates; open-loop interventions rejected |

The milestone is recorded as a file rather than a git tag because the current working directory is not a git repository.

---

## 2. External escalation packages

Two Arena escalation packages have been finalized in `external_reviews/`.

### 2.1 Procedural cube fallback invalidity

**Package:** `external_reviews/procedural_cube_fallback_invalidity_escalation.md`
**Related tracker:** `reports/ARENA_ISSUE_TRACKER.md` §2.5
**Status:** Ready to submit / attach to IsaacLab-Arena#807

Core ask:

1. Is the procedural fallback intended to be physically interactive?
2. Why is `collision_enabled=False`?
3. Why is the bounding box invalid / degenerate?
4. Should `cube_goal_pose` fail hard when `dex_cube` is missing?
5. What is the intended replacement for local diagnostic object variants?

Evidence snapshot:

| Task | Valid Rate | Collision Enabled | BBox Valid |
|---|---:|---:|---:|
| `goal_pose_procedural_cube_ood` | 0.0% | 0.0% | 0.0% |
| `goal_pose_procedural_cube_dex_size` | 0.0% | 0.0% | 0.0% |
| `goal_pose_procedural_cube_large` | 0.0% | 0.0% | 0.0% |

Audit artifact: `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`

**Ready-to-post comment:** see §4.1 below.

### 2.2 Large-yaw torsional slip

**Package:** `external_reviews/large_yaw_torsional_slip_escalation.md`
**Related tracker:** `reports/ARENA_ISSUE_TRACKER.md` §5
**Status:** Ready to submit as a new or existing Arena P1 issue

Core ask:

1. What are the intended gripper friction / force / contact parameters for `dex_cube`?
2. Is in-hand yaw rotation expected to work for 90° / 120°?
3. Are force/contact readings exposed in IsaacLab-Arena?
4. Is there an official manipulation strategy for large-yaw cube reorientation?
5. Can `franka_ik_abs` or an official absolute-pose IK config be accepted?

Evidence snapshot:

| Target Yaw | Lifted Rate | Orient Achieved | Dominant Category |
|---|---:|---:|---:|
| π/2 (1.5708) | 100% | 10% | `torsional_slip` 9, `eef_yaw_failure` 9 |
| 2π/3 (2.0944) | 100% | 0% | `torsional_slip` 18, `eef_yaw_failure` 2 |

Ablation artifact: `data_v17/ablations/large_yaw_intervention/aggregate_summary.json`

**Ready-to-post comment:** see §4.2 below.

---

## 3. Local claim boundary

Until the Arena team responds:

- **Do not claim** 100/100 official robustness (seed 24 is still open).
- **Do not claim** procedural-cube OOD skill evaluation.
- **Do not claim** large-yaw orientation solution.
- **Do not claim** validated transferable skill.
- **Can claim** rigorous diagnosis, reproducible traces, 99/100 official success, and two ready-to-submit escalation packages.

---

## 4. Ready-to-submit GitHub markdown

The following comments are ready to be posted to IsaacLab-Arena. They are reproduced here for convenience; the canonical versions are in the escalation packages.

### 4.1 Procedural fallback invalidity comment

```markdown
## Procedural cube fallback is not a valid interactive rigid body

We audited the procedural cube fallback used when `dex_cube` is not available in the local Docker runtime.

**Result:** the fallback is not a valid interactive object for manipulation benchmarks.

| Task | Valid Rate | Collision Enabled | BBox Valid | Rigid Body | Index Consistency |
|---|---:|---:|---:|---:|---:|
| `goal_pose_procedural_cube_ood` | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |
| `goal_pose_procedural_cube_dex_size` | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |
| `goal_pose_procedural_cube_large` | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |

Error distribution: `invalid_bbox`: 110, `collision_disabled`: 110 (10 seeds × 11 steps per task).

**Reproduction:**
```bash
python scripts/diagnostics/run_procedural_object_validity_audit.py \
  --tasks \
    configs/tasks/goal_pose_procedural_cube_ood.yaml \
    configs/tasks/goal_pose_procedural_cube_dex_size.yaml \
    configs/tasks/goal_pose_procedural_cube_large.yaml \
  --seeds 0:9 \
  --out-dir data_v17/diagnostics/procedural_object_validity_audit \
  --cleanup
```

**Ask:**
1. Is the procedural fallback intended to be physically interactive?
2. Why is `collision_enabled=False`?
3. Why is the bounding box invalid / degenerate?
4. Should `cube_goal_pose` fail hard when `dex_cube` is missing?
5. What is the intended replacement for local diagnostic object variants?

We are blocking all procedural-cube OOD claims until `valid_rate = 1.0`.
```

### 4.2 Large-yaw torsional slip comment

```markdown
## Large-yaw in-hand torsional slip cannot be fixed by open-loop policy interventions

We diagnosed large-yaw orientation failures on `cube_goal_pose` with the official `dex_cube` asset and `franka_ik_abs` embodiment.

**Result:** the object lifts reliably (100%) but orientation achievement is near zero at π/2 (10%) and 2π/3 (0%). The dominant failure mode is torsional slip inside the pinch grasp.

We tested four open-loop structural interventions:
- `grasp_at_target_yaw` — align gripper to target yaw before descending.
- `low_height_incremental_yaw` — small lift height, incremental yaw alignment.
- `table_push_align` — press object against table while applying yaw torque.
- `table_push_align_tuned` — longer push-align, higher z-offset, faster yaw step, stronger lateral oscillation, reduced downward pressure.

None improved `orientation_achieved_rate` by ≥20% relative. Interventions that fix pre-grasp yaw authority convert `eef_yaw_failure` into `torsional_slip` without improving net success.

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
1. What are the intended gripper friction / force / contact parameters for `dex_cube`?
2. Is in-hand yaw rotation expected to work for 90° / 120°?
3. Are force/contact readings exposed in IsaacLab-Arena?
4. Is there an official manipulation strategy for large-yaw cube reorientation?
5. Can `franka_ik_abs` or an official absolute-pose IK config be accepted?

We are blocking all large-yaw success claims until the contact/gripper surface is clarified.
```

---

## 5. Next steps

1. **Pending user approval:** submit the two comments above to IsaacLab-Arena.
2. **v1.8 Sprint 1:** seed 24 post-lift slip forensics.
3. **v1.8 Sprint 2:** minimal seed 24 fix + 0:99 + 100:199 regression.
4. **v1.8 Sprint 3:** build valid OOD cube benchmark as a local replacement for the invalid procedural fallback.
5. Continue closed-loop slip detection and recovery work while waiting for Arena feedback.

---

*ROSClaw-Darwin v1.7 milestone and escalation status — finalized 2026-06-21.*
