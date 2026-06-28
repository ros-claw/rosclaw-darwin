# ROSClaw-Darwin Demo Map

This document maps the five v1.0 demos to existing evidence artifacts.

---

## Demo A: Official GoalPose Baseline

**What it shows:** Darwin can produce a clean official-asset benchmark baseline with validity gating and failure classification.

**Evidence source:**
- `data_v20/official/dex_cube_goal_pose_100_seed_post_reachability/` or equivalent official dex_cube run.

**Key numbers:**
- 99/100 success on `franka_ik_abs` + reachability-promoted v3 policy.
- 0 asset fallback.
- 0 physics anomaly.
- 0 approach collision.

**CLI:**
```bash
rosclaw darwin validate-env --task configs/tasks/goal_pose_dex_cube_official.yaml --seeds 0:4
rosclaw darwin run --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:99
```

**Evidence card:** `cards/official_goalpose_baseline.card.yaml`

**Allowed claim:** Darwin can validate benchmark environments and produce clean official baselines.

**Blocked claim:** universal robot capability, official Arena leaderboard result.

---

## Demo B: Seed24 Micro-Recovery

**What it shows:** Darwin can promote a local recovery to `candidate_recovery` only after paired no-regression evidence.

**Evidence source:**
- `data_v20/paired/official_seed24_micro_recovery_0_199/paired_summary.json`

**Key numbers:**
- rescued seeds: 24, 198
- `newly_failed_count = 0`
- `candidate_success_rate = 0.965`
- `baseline_success_rate = 0.955`
- FTH v3.4 promotion = `candidate_recovery`

**CLI:**
```bash
rosclaw darwin diagnose --run data/darwin/runs/official_goalpose_baseline/per_seed/seed_024
rosclaw darwin pair-eval \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --baseline configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --candidate configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml \
  --seeds 0:199
rosclaw darwin promote --candidate seed24_micro_recovery --paired .../paired_summary.json
rosclaw darwin card --candidate seed24_micro_recovery
```

**Evidence card:** `cards/seed24_micro_recovery.card.yaml`

**Allowed claim:** Darwin can promote a candidate recovery based on paired no-regression evidence.

**Blocked claim:** validated transferable skill, official 100/100 solved.

---

## Demo C: Procedural Fallback Invalidity

**What it shows:** Darwin's validity gate catches an invalid environment before it pollutes skill evaluation.

**Evidence source:**
- Object validity audit of procedural cube fallback.

**Key numbers:**
- `collision_enabled = false`
- `bbox_valid = false`
- `valid_rate = 0`

**CLI:**
```bash
rosclaw darwin validate-env --task configs/tasks/goal_pose_procedural_cube_fallback.yaml --seeds 0:4
```

**Evidence card:** `cards/procedural_fallback_invalid_environment.card.yaml`

**Allowed claim:** Darwin prevents invalid benchmark environments from polluting skill evaluation.

**Blocked claim:** policy failed on procedural cube, cross-object generalization failed.

---

## Demo D: Large-Yaw Torsional Slip

**What it shows:** Darwin can refuse false recovery promotion and route a failure to `blocked_external`.

**Evidence source:**
- Large-yaw slip diagnostic aggregate.
- FTH v3.4 evidence status.

**Observations:**
- End-effector yaw is controllable.
- Object yaw initially follows.
- After lift, torsional slip occurs.
- Kinematic recovery is ineffective.
- Route = `blocked_external`.

**CLI:**
```bash
rosclaw darwin diagnose --run data/darwin/runs/large_yaw_yaw_1.57/per_seed/seed_000
rosclaw darwin promote --candidate large_yaw_recovery --paired ...
```

**Evidence card:** `cards/large_yaw_torsional_slip_blocked_external.card.yaml`

**Allowed claim:** Darwin can block false recovery promotion and route externally blocked failures.

**Blocked claim:** large-yaw solved, slip recovery validated.

---

## Demo E: Valid OOD Suite

**What it shows:** Darwin can create valid diagnostic OOD suites and separate valid negative evidence from invalid-environment artifacts.

**Evidence source:**
- `rosclaw_valid_cube` variants.
- Validity audit pass.
- ObjectGeometryAdapter evaluation showing no measurable gain.

**Key observations:**
- Valid OOD benchmark available.
- No transferable skill claim.
- Negative result is honest and valid.

**CLI:**
```bash
rosclaw darwin validate-env --task configs/tasks/goal_pose_rosclaw_valid_cube.yaml --seeds 0:4
rosclaw darwin run --task configs/tasks/goal_pose_rosclaw_valid_cube.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:49
```

**Evidence card:** `cards/valid_ood_suite.card.yaml`

**Allowed claim:** Darwin can create valid diagnostic OOD suites and separate valid negative evidence from invalid artifacts.

**Blocked claim:** OOD adaptation success, transferable skill validated.

---

## Demo pack quick start

```bash
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin
bash demo_pack/commands.sh
```

This runs smoke-mode versions of the key CLI commands and produces evidence cards under `demo_outputs/`.
