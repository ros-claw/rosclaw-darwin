# Slip-Aware Recovery Ablation Report

**Date:** 2026-06-23  
**Sprint:** v1.8 Sprint 6  
**Status:** Pilot complete — **minimum bar met, high-quality bar not met**. Closed-loop recovery triggers reliably and preserves lift, but no strategy improves large-yaw orientation success in this 3-seed pilot.

---

## 1. Goal

Wire the Sprint 5 kinematic `SlipMonitor` into the `heuristic_servo_goal_pose` state machine and compare closed-loop recovery strategies against the no-monitor baseline on the official `dex_cube` task at large target yaws.

The central question: *can detect → pause / regrip / lower / place-push / abort recover from in-hand torsional slip better than the open-loop baseline?*

---

## 2. Experiment Design

### 2.1 Task and policy

| Item | Value |
|---|---|
| Task | `configs/tasks/goal_pose_dex_cube_official.yaml` |
| Base policy | `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` |
| Embodiment | `franka_ik_abs` |
| Target yaws | 1.5708 rad (π/2), 2.0944 rad (2π/3) |
| Seeds | 0, 1, 2 |
| Conditions | `baseline`, `pause_stabilize`, `lower_regrip`, `abort_residual_yaw`, `place_push_correct`, `best_combined` |

The seed count was reduced from the planned 0:19 to 0:2 after parallel GPU runs produced many `no_trace` failures. Serial execution with `--gpus all` is stable; the trade-off is a small-N pilot that can reliably detect large regressions but cannot claim tight statistics.

### 2.2 Recovery strategies

All strategies are implemented inside `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` and are triggered by the container-side `SlipMonitor` proxy.

| Condition | Behaviour |
|---|---|
| `baseline` | `enable_slip_monitor=false`; policy is unchanged v3 reachability-promoted. |
| `pause_stabilize` | On slip event: pause for `slip_recovery_pause_steps`, keep gripper closed, reduce EEF motion. |
| `lower_regrip` | On slip event: lower the gripper, re-close gripper, then lift slowly. |
| `abort_residual_yaw` | On slip event: abort yaw reorientation, finish with whatever orientation is held. |
| `place_push_correct` | On slip event: place object on table, push-align to target yaw, then lift again. |
| `best_combined` | Try `pause_stabilize`, then `lower_regrip`, then fall back to `place_push_correct`. |

### 2.3 Outputs

- `data_v18/ablations/slip_aware_recovery_pilot/per_run_results.csv`
- `data_v18/ablations/slip_aware_recovery_pilot/aggregate_summary.json`

The primary success metric for large-yaw recovery is `orientation_achieved_rate` (object yaw within tolerance of target at episode end). Secondary metrics: `lifted_rate`, `env_success_rate`, `recovery_triggered_rate`, and mean `yaw_coupling_score`.

---

## 3. Aggregate Results

### 3.1 Orientation achieved rate

| Condition | Yaw π/2 | Yaw 2π/3 |
|---|---:|---:|
| baseline | 33.3% (1/3) | 0% (0/3) |
| pause_stabilize | 0% (0/3) | 0% (0/3) |
| lower_regrip | 33.3% (1/3) | 0% (0/3) |
| abort_residual_yaw | 0% (0/3) | 0% (0/3) |
| place_push_correct | 33.3% (1/3) | 0% (0/3) |
| best_combined | 33.3% (1/3) | 0% (0/3) |

### 3.2 Lifted rate and environment success

| Condition | Yaw π/2 lifted | Yaw 2π/3 lifted | Env success π/2 | Env success 2π/3 |
|---|---:|---:|---:|---:|
| baseline | 100% | 100% | 100% | 100% |
| pause_stabilize | 100% | 100% | 100% | 100% |
| lower_regrip | 100% | 100% | 100% | 100% |
| abort_residual_yaw | **0%** | **0%** | **0%** | **0%** |
| place_push_correct | 100% | 100% | 100% | 100% |
| best_combined | 100% | 100% | 100% | 100% |

### 3.3 Recovery trigger and mean yaw coupling

| Condition | Recovery triggered π/2 | Recovery triggered 2π/3 | Mean coupling π/2 | Mean coupling 2π/3 |
|---|---:|---:|---:|---:|
| baseline | 0% | 0% | 0.471 | 0.991 |
| pause_stabilize | 100% | 100% | 0.543 | 0.975 |
| lower_regrip | 100% | 100% | 0.485 | 0.950 |
| abort_residual_yaw | 100% | 100% | 0.368 | 0.368 |
| place_push_correct | 100% | 100% | 0.489 | 0.804 |
| best_combined | 100% | 100% | 0.489 | 0.804 |

### 3.4 Category distribution (per condition × yaw)

- **baseline π/2:** 2 `torsional_slip`, 1 `success`
- **baseline 2π/3:** 3 `torsional_slip`
- **pause_stabilize π/2:** 2 `torsional_slip`, 1 `eef_yaw_failure`
- **pause_stabilize 2π/3:** 3 `torsional_slip`
- **lower_regrip π/2:** 2 `torsional_slip`, 1 `success`
- **lower_regrip 2π/3:** 2 `torsional_slip`, 1 `eef_yaw_failure`
- **abort_residual_yaw π/2 & 2π/3:** 3 `not_lifted` each
- **place_push_correct π/2:** 2 `eef_yaw_failure`, 1 `success`
- **place_push_correct 2π/3:** 3 `torsional_slip`
- **best_combined:** identical to `place_push_correct` because the fallback path ended at `place_push_correct` for every seed.

---

## 4. Key Findings

1. **No strategy improves orientation success over baseline in this pilot.**
   - π/2 baseline already succeeds 1/3; every recovery strategy also succeeds 1/3 or 0/3.
   - 2π/3 baseline fails 3/3 with `torsional_slip`; every strategy also fails 3/3.

2. **`abort_residual_yaw` is destructive.**
   - It aborts the lift trajectory early and ends with `not_lifted` on all 6 seeds, dropping env success to 0%. This condition is rejected.

3. **The other strategies preserve lift and env success.**
   - `pause_stabilize`, `lower_regrip`, `place_push_correct`, and `best_combined` all keep `lifted_rate = 1.0` and `env_success_rate = 1.0`.
   - They therefore meet the **minimum** Sprint 6 bar (recovery does not break the official task).

4. **Mean yaw-coupling scores do not show a clear recovery benefit.**
   - At 2π/3, `place_push_correct` and `best_combined` reduce mean coupling from 0.99 (baseline) to 0.80, but this reduction does not translate into a successful orientation.
   - At π/2, coupling scores stay roughly at baseline levels.

5. **Recovery triggers reliably.**
   - For all non-baseline conditions, `recovery_triggered_rate = 1.0`. The `SlipMonitor` → policy wiring is functional.

6. **`best_combined` collapses to `place_push_correct` here.**
   - Because the first two stages did not resolve the slip for any seed, the fallback was always exercised. The aggregate is identical to `place_push_correct`.

---

## 5. Honest Assessment

| Criterion | Sprint 6 target | Pilot result | Verdict |
|---|---|---|---|
| Recovery does not reduce `lifted_rate` | maintain | maintained for all except `abort_residual_yaw` | **Pass** |
| Some strategy reduces slip severity or improves orientation | any improvement | no orientation improvement; coupling slightly lower for `place_push_correct` at 2π/3 | **Partial / not conclusive** |
| π/2 `orientation_achieved_rate` improves ≥20% relative | ≥40% | 33% (same as baseline) | **Not met** |
| 2π/3 shows non-zero improvement | >0% | 0% | **Not met** |
| False-positive recovery does not break success traces | no regression | no clear regression beyond `abort_residual_yaw` | **Pass** |

**Conclusion:** The closed-loop slip-recovery infrastructure works (monitor fires, policy reacts, lift is preserved), but the *specific kinematic strategies tested do not solve large-yaw torsional slip*. This is consistent with the earlier open-loop rejection: once the object has twisted in the gripper, purely kinematic corrections are not enough to re-engage and reorient it.

---

## 6. Limitations

- **Small sample:** 3 seeds per condition. The pilot can detect catastrophic regressions (e.g. `abort_residual_yaw`) but is underpowered for small improvements.
- **Kinematic proxy only:** no force/contact feedback, no gripper force control, no Arena-side friction tuning.
- **`abort_residual_yaw` implementation is too aggressive:** aborting yaw also aborts the lift motion in the current state machine. A safer version would complete the lift and only skip the final yaw alignment.
- **Slip is detected very early (APPROACH, step ~11–13):** the object-EEF yaw separation crosses threshold before the object is fully lifted, so recovery actions may be triggered before a stable grasp is established.

---

## 7. Files Used / Added

- `scripts/ablations/run_slip_aware_recovery_ablation.py`
- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` (slip-recovery states)
- `rosclaw_darwin/evaluation/slip_monitor.py`
- `data_v18/ablations/slip_aware_recovery_pilot/aggregate_summary.json`
- `data_v18/ablations/slip_aware_recovery_pilot/per_run_results.csv`
- `reports/SLIP_AWARE_RECOVERY_ABLATION_REPORT.md` (this report)

---

## 8. Next Steps

1. **Do not promote any of these recovery strategies** to the official v1.8 policy based on this pilot.
2. **Reject `abort_residual_yaw`** in its current form (breaks lift).
3. **Consider a larger 0:19 serial run** only if a physically different recovery idea is implemented (e.g. force-based regrasp, gripper force modulation, or Arena-side contact/friction changes).
4. **Update the FailureToHint v3.2 rule set** to record that `torsional_slip` on `dex_cube` at large yaw currently has no validated closed-loop recovery; fallback remains `abort_safe` or human escalation.
5. **Proceed to Sprint 9 final v1.8 status report** with this evidence classified as **Level B — preliminary / not proven** for large-yaw closed-loop recovery.
