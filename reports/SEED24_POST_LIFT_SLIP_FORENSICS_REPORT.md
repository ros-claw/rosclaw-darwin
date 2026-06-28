# Seed 24 Post-Lift Slip Forensics Report

**Date:** 2026-06-21

**Status:** Sprint 1 of v1.8 — **10-repeat forensic analysis complete. Seed 24 failure is deterministic `grip_force_insufficient`, not a stochastic physics drop.**

**Purpose:** Answer six forensic questions about the only remaining official failure in the v1.7 100-seed benchmark:

1. Is the failure deterministic or stochastic?
2. In which phase does the object actually fall?
3. What is the gripper/closure signature compared with successful seeds?
4. What is different about seed 24 at the moment of grasp?
5. Is the root cause insufficient force, torsional slip, lift acceleration, or a grasp-geometry mismatch?
6. What is the minimal, non-overfit intervention to test in Sprint 2?

---

## 1. Method

**Script:** `scripts/diagnostics/run_seed24_slip_forensics.py`

**Module:** `rosclaw_darwin/evaluation/slip_forensics.py`

**Task:** `configs/tasks/goal_pose_dex_cube_official.yaml`

**Policy:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`

**Seed:** 24

**Repeats:** 10 (serial, fresh container per repeat, private trace directory)

**Comparison baseline:** successful official seeds 0–4 from `data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/`

**Key trace fields per step:**

- `phase`
- `object_pos`, `object_quat`, `object_yaw`, `object_z`
- `eef_pos`, `eef_quat`, `eef_yaw`
- `gripper_pos`, `gripper_cmd`
- `object_height_delta`, `object_z_velocity`
- `object_eef_distance`, `object_eef_yaw_delta`
- `object_yaw_error`

**Classification taxonomy:** `classify_seed24_slip` returns one of:

- `vertical_slip_after_lift`
- `torsional_slip_after_lift`
- `hold_instability`
- `grip_force_insufficient`
- `lift_acceleration_too_high`
- `orientation_realign_induced_slip`
- `metric_false_negative`
- `success`
- `unknown`

The classifier treats a gripper that never reaches the blocked closure width (`gripper_pos_min_while_lifted > 0.035`) as `grip_force_insufficient`, regardless of when the object finally becomes visible as dropped.

---

## 2. Command

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_seed24_slip_forensics.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seed 24 \
  --repeat 10 \
  --out-dir data_v18/diagnostics/seed24_slip_forensics \
  --cleanup
```

---

## 3. Aggregate Results

**Artifact:** `data_v18/diagnostics/seed24_slip_forensics/aggregate_summary.json`

| Metric | Seed 24 (10 repeats) |
|---|---:|
| Total repeats | 10 |
| Valid repeats | 10 |
| Success repeats | 0 |
| Dominant category | `grip_force_insufficient` (10/10) |
| Deterministic | **Yes** |
| Mean max object z | 0.5142 m |
| Mean step of max height | 468 |
| Mean drop step | 1695 |
| Mean final object z | 0.0210 m |
| Mean gripper pos min (global) | 0.0208 m |
| Mean gripper pos min **while lifted** | 0.0388 m |
| Gripper blocked while lifted | 0/10 |
| Mean object yaw error final | 3.1416 rad |
| Mean max object z velocity down | -0.0554 m/step |

The per-repeat values are identical to the displayed precision, confirming that the failure is fully reproducible under the promoted configuration.

---

## 4. Representative Trace Details

**Repeat:** `seed024_repeat00` (selected as representative)

**Trace:** `data_v18/diagnostics/seed24_slip_forensics/seed024_repeat00/trace.jsonl`

### Phase trace

| Phase | Start Step | End Step |
|---|---:|---:|
| APPROACH | 0 | 316 |
| DESCEND | 317 | 332 |
| GRASP | 333 | 397 |
| LIFT | 398 | 459 |
| VERIFY_OBJECT_FOLLOWING | 460 | 464 |
| REORIENT | 465 | 1429 |
| STABILIZE | 1430 | 1439 |
| ALIGN | 1440 | 2499 |

### Key quantities at critical steps

| Step / Phase | object_z | eef_z | gripper_pos | gripper_cmd | object_yaw | eef_yaw | object_eef_distance |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 / APPROACH | 0.2000 | 0.2500 (start) | 0.0400 | — | -0.3324 | -3.1416 (start) | ~0.97 |
| 333 / GRASP start | 0.0210 | 0.0253 | 0.0399 | -1.0 | ~0.0000 | 2.6868 | 0.0040 |
| 397 / GRASP end | 0.0210 | 0.0253 | 0.0388 | -1.0 | ~0.0000 | 2.6905 | 0.0040 |
| 398 / LIFT start | 0.0210 | 0.0253 | 0.0388 | -1.0 | ~0.0000 | 2.6905 | 0.0040 |
| 459 / LIFT end | 0.4598 | 0.4688 | 0.0388 | -1.0 | 0.0226 | 2.6605 | 0.0055 |
| 468 / Max height | 0.5142 | — | 0.0388 | -1.0 | — | — | — |
| 1695 / Drop in ALIGN | 0.4643 → falling | — | 0.0388 → closing after drop | -1.0 | — | — | — |
| 2499 / Final | 0.0210 | — | 0.0001 | -1.0 | -0.9938 | 1.6709 | — |

### Observations from the representative trace

- The object is **lifted** cleanly to 0.514 m (step 468), so the failure is not an inability to start the lift.
- The drop is first detected in **ALIGN** at step 1695, long after LIFT.
- The gripper is commanded to close (`gripper_cmd = -1.0`) throughout GRASP, LIFT, REORIENT, STABILIZE, and ALIGN, but the actual `gripper_pos` stays at **~0.0388** until the object has already fallen.
- The blocked closure width for the dex_cube is ~0.024; seed 24 never reaches it.
- The end-effector is only ~4 mm from the object center, so the problem is **not** a gross positioning failure.

---

## 5. Comparison with Successful Seeds 0–4

| Metric | Seed 24 (mean) | Successful seeds 0–4 (mean) |
|---|---:|---:|
| Env success rate | 0.00 | 1.00 |
| Final object z | 0.0210 m | 0.4625 m |
| Max object z | 0.5142 m | 0.5181 m |
| Gripper pos min while lifted | **0.0388 m** | **0.0240 m** |
| Gripper blocked while lifted | 0/10 | 5/5 |
| Object z at GRASP → LIFT | ~0.0210 m | ~0.0253–0.0279 m |
| Object_eef_distance_min | 0.0040 m | 0.0023–0.0059 m |
| Object yaw error final | 3.1416 rad | 2.3270 rad |

The decisive discriminator is the gripper closure state:

- **Successful seeds:** the gripper reaches the cube-blocked width (~0.024) during GRASP and stays there.
- **Seed 24:** the gripper stays at the open-air width (~0.039) for the entire lifted phase.

All other kinematic proxies (max height, distance to object, approach duration) are similar, which rules out a fundamental reachability or positioning bug as the seed-24-specific cause.

---

## 6. Answers to the Six Forensic Questions

### Q1. Is the failure deterministic or stochastic?

**Deterministic.**

All 10 repeats produced identical values (to the displayed precision) for:

- failure category (`grip_force_insufficient`)
- max height (0.5142 m)
- step of max height (468)
- drop step (1695)
- gripper pos min while lifted (0.0388)
- final object z (0.0210)

The seed-24 failure is therefore a **reproducible structural failure**, not a physics- or contact-noise instability. This means it is appropriate to attempt a targeted, minimal fix, provided the fix is validated on 0:99 and 100:199 without regression.

### Q2. In which phase does the object actually fall?

The catastrophic vertical drop is first detected in **ALIGN** at step 1695.

However, the causal failure occurs much earlier:

- The gripper never blocks during **GRASP** (steps 333–397).
- The object is lifted anyway (steps 398–468) because light friction or intermittent contact is enough to carry it.
- The object remains near the max height through **REORIENT** and **STABILIZE**.
- Once **ALIGN** begins, the residual motion or reorientation torque exceeds the weak frictional hold, and the cube falls.

So the *reported* drop phase is ALIGN, but the *root* phase is GRASP.

### Q3. What is the gripper/closure signature compared with successful seeds?

| Quantity | Seed 24 | Successful seeds |
|---|---|---|
| Gripper close command | `-1.0` throughout | `-1.0` or equivalent throughout |
| Actual gripper pos while lifted | ~0.039 (open) | ~0.024 (blocked by cube) |
| Blocked? | **No** | **Yes** |
| Release before drop? | Not applicable (never blocked) | Not observed in baseline |

The signature is a **missed grasp**: the fingers are commanded to close but never reach the cube-blocked width. This is mechanically different from a successful grasp that later reopens (`grip_force_insufficient` due to release) or a successful grasp that slips while remaining blocked (`torsional_slip` / `hold_instability`).

### Q4. What is different about seed 24 at the moment of grasp?

At the GRASP → LIFT transition:

| Quantity | Seed 24 | Seed 0 | Seed 1 |
|---|---:|---:|---:|
| object_z | 0.0210 m | 0.0279 m | 0.0253 m |
| eef_z | 0.0253 m | 0.0424 m | 0.0249 m |
| gripper_pos | 0.0388 | 0.0244 | 0.0239 |
| eef_x − object_x | +0.0007 m | +0.0061 m | −0.0010 m |
| eef_y − object_y | −0.0100 m | +0.0062 m | +0.0023 m |
| eef_yaw at GRASP | 2.6905 rad | 2.6975 rad | 2.9160 rad |

The most consistent difference is the **object height at grasp**: seed 24's object settles at ~0.021 m, while successful seeds are at ~0.025–0.028 m. The lateral offsets are within the normal successful range after projecting into the gripper frame, and the relative yaw at GRASP is comparable to successful seeds. This points to a **grasp-height / contact-geometry** issue: the fingers are not engaging the cube faces at the lower object height, so the gripper closes to the open-air limit instead of the blocked width.

### Q5. Is the root cause insufficient force, torsional slip, lift acceleration, or a grasp-geometry mismatch?

**Root cause: grasp-geometry mismatch leading to `grip_force_insufficient`.**

Evidence against the other hypotheses:

- **Torsional slip after lift:** `max_object_eef_yaw_delta` is 1.917 rad, but torsional slip is a *consequence* of the object not being firmly grasped, not the primary cause. The classifier does not label it `torsional_slip_after_lift` because the gripper was never blocked.
- **Lift acceleration too high:** The drop happens at step 1695, more than 1200 steps after the lift ended. There is no rapid vertical drop during or right after LIFT.
- **Hold instability:** The object stays at height for ~1200 steps, so this is not a slow contact-relaxation failure in HOLD.
- **Metric false negative:** Final object z is 0.021 m, well below the success height band; the metric is correctly reporting failure.

The fundamental issue is that the gripper fingers do not make the face-to-face contact required to reach the blocked width, even though the end-effector is positioned within 4 mm of the object center.

### Q6. What is the minimal, non-overfit intervention to test in Sprint 2?

Because the failure is deterministic and localized to GRASP geometry, the Sprint 2 ablation should test **grasp-geometry corrections** rather than global parameter sweeps. Candidate minimal interventions:

1. **Adaptive DESCEND target / grasp height compensation**  
   Close the residual z-gap between the fingers and the object when the observed object_z is low (e.g., seed 24's 0.021 m). This can be done by descending to `object_z + finger_center_offset` rather than a fixed world-z target.

2. **Re-enable `pre_grasp_orient` with absolute-quaternion control**  
   The promoted config disables pre-grasp orientation to isolate reachability effects. For seed 24, aligning the gripper yaw with the cube faces before GRASP may ensure flat-face contact and produce the blocked closure width.

3. **Grasp verification + retry**  
   At the end of GRASP, check `gripper_pos < blocked_threshold`. If not blocked, re-enter a short DESCEND/GRASP cycle with a small vertical or lateral adjustment instead of proceeding to LIFT.

4. **Longer squeeze / higher force (lower priority)**  
   Increasing `grasp_squeeze_steps` or lowering `gripper_close_threshold` is unlikely to help, because the fingers are not touching the cube faces; squeezing empty air harder will not change the aperture.

The Sprint 2 runner (`scripts/ablations/run_seed24_slip_fix_ablation.py`) will compare baseline against these conditions on 10 repeats of seed 24. Only a condition that achieves ≥8/10 success and does not regress 0:99 or 100:199 will be promoted.

---

## 7. Honest Claim Boundary

- **Can claim:** Seed 24 failure is deterministic and classified as `grip_force_insufficient`; the gripper never reaches the blocked closure width while the object is lifted.
- **Cannot claim yet:** Any specific fix is guaranteed to work, because the grasp-geometry hypothesis still needs ablation validation.
- **Cannot claim:** The failure is a pure force/torque limitation; the evidence points to contact geometry, not insufficient motor effort.

---

## 8. Artifacts

- Aggregate summary: `data_v18/diagnostics/seed24_slip_forensics/aggregate_summary.json`
- Per-repeat CSV: `data_v18/diagnostics/seed24_slip_forensics/per_repeat_results.csv`
- Representative trace: `data_v18/diagnostics/seed24_slip_forensics/seed024_repeat00/trace.jsonl`
- Forensics module: `rosclaw_darwin/evaluation/slip_forensics.py`
- Runner: `scripts/diagnostics/run_seed24_slip_forensics.py`
- Official v1.7 baseline: `data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/`

---

## 9. Next Step

Proceed to **Sprint 2: Minimal Seed 24 Fix + Official Regression**. The first experiment is the grasp-height / pre-grasp-orientation ablation on seed 24 with 10 repeats, followed by 0:99 and 100:199 regression if a candidate passes the promotion threshold.
