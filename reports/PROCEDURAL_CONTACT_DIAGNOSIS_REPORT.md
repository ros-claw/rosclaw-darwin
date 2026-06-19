# Procedural Contact Diagnosis Report

**Date:** 2026-06-19

**Goal:** Determine the direct contact-level reason the procedural-cube fallback does not lift, using the structural contact-proxy trace fields introduced in FailureToHint v3.1.

---

## 1. Context

The procedural OOD fallback fails before any meaningful grasp contact. The v3.1 structural regrasp state machine (`reports/STRUCTURAL_FAILURE_TO_HINT_V31_REPORT.md`) added:

- `CONTACT_VERIFY` — hold pose and classify `contact_proxy`.
- `LIFT_VERIFY` — short guarded lift to measure `lift_response_z`.
- `REGRASP` — retry with xy offsets if lift response is insufficient.

Contact-proxy classes:

| proxy | meaning |
|---|---|
| `no_contact` | gripper closed but did not engage the object |
| `pushed_away` | object moved away during closure |
| `likely_contact` | gripper blocked, object stays near |
| `weak_contact_no_lift` | contact inferred but object does not follow lift |
| `unknown` | not enough data |

---

## 2. Observations

A single-seed baseline vs regrasp run on `goal_pose_procedural_cube_ood.yaml` showed:

| seed | condition | status | success | descend_exit_rate | object_height_delta | contact_proxy |
|---|---|---:|---:|---:|---:|---|
| 0 | baseline | completed | 0.0 | 0.0 | -6250.68 m | {} |
| 0 | regrasp | completed | 0.0 | 0.0 | -6250.68 m | {} |

The `contact_proxy_distribution` is empty because the policy never reaches `GRASP`/`CONTACT_VERIFY`/`LIFT_VERIFY`. The failure occurs in or before `DESCEND`:

- `descend_exit_rate = 0.0`
- `object_height_delta` is a physics anomaly (object falls through the floor / flies away).

This is consistent with the earlier asset-fidelity conclusion: the procedural fallback object has different spawn geometry, origin, or contact properties that prevent the gripper from ever establishing the same reachable/contact relationship as the official `dex_cube`.

---

## 3. What contact diagnosis would need

For `contact_proxy` to produce actionable signal, the policy must first reach `GRASP`. Two possible paths:

1. **Find a procedural seed (or adjust geometry) where DESCEND succeeds.**
   - Use `ObjectGeometryAdapter` to enlarge thresholds / lower approach until the gripper reaches the object.
   - Then run `scripts/diagnostics/run_procedural_contact_diagnosis.py` to see whether the issue is `no_contact`, `pushed_away`, or `weak_contact_no_lift`.

2. **Fix the asset-fidelity root cause.**
   - If the procedural cube's USD/spawn config differs from `dex_cube`, no amount of contact diagnosis inside the current policy will lift it.
   - This remains the external dependency documented in `reports/ARENA_ISSUE_TRACKER.md`.

---

## 4. Honest conclusion

1. The procedural OOD object fails **before contact**: `DESCEND` does not exit, so `contact_proxy` is empty.
2. The regrasp state machine cannot help because it is only triggered after `GRASP`; the failure is upstream.
3. Contact-level diagnosis is therefore **blocked by the same asset-fidelity issue** that blocked v3/v3.1 parameter hints.
4. Next step: either (a) tune `ObjectGeometryAdapter` until at least some procedural seeds reach `GRASP`, or (b) push the asset-fidelity question to the Arena team.

---

## 5. Files changed

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `scripts/diagnostics/run_procedural_contact_diagnosis.py`
- `reports/PROCEDURAL_CONTACT_DIAGNOSIS_REPORT.md` (this report)
