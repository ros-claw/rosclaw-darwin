# Real Arena Baseline Improvement Report

## Objective

Move ROSClaw-Darwin's `lift_object` baseline from **0 % real success rate** to a
**measurable non-zero success** on IsaacLab-Arena in Docker mode. The work
focused on two new policies:

- `HeuristicServoLiftPolicy` — closed-loop servo using `eef_pos`, `eef_quat`,
  `object_pos`, `gripper_pos`, and the command target from `task_obs`.
- `CheatLiftPolicy` — sanity-check policy that teleports the object to the
  command target to verify the Arena eval pipeline can report non-zero
  `success_rate`.

## Test Setup

| Setting | Value |
|---|---|
| Environment | `ROSCLAW_ARENA_MODE=docker` |
| Task | `examples/tasks/native/lift_object.yaml` |
| Suite | `/tmp/lift_object_baseline_suite.yaml` (single task) |
| Episodes | 5 per policy |
| Docker image | `rosclaw-darwin:arena-base` |
| GPU | NVIDIA RTX A6000 |

Commands:

```bash
export ROSCLAW_ARENA_MODE=docker

darwin suite run --suite /tmp/lift_object_baseline_suite.yaml \
  --adapter arena --policy configs/policies/cheat_lift.yaml \
  --loops 1 --episodes 5 --out /tmp/rosclaw_data/arena_real/final_lift_cheat

darwin suite run --suite /tmp/lift_object_baseline_suite.yaml \
  --adapter arena --policy configs/policies/heuristic_servo_lift.yaml \
  --loops 1 --episodes 5 --out /tmp/rosclaw_data/arena_real/final_lift_servo
```

## Results

| Policy | Task | Status | `success_rate` | Notes |
|---|---|---|---|---|
| `cheat_lift` | `darwin_mvp_03_lift_object` | completed | **1.00** | Teleports object to command target; verifies pipeline |
| `heuristic_servo_lift` | `darwin_mvp_03_lift_object` | completed | **0.00** | Progress visible but did not reach object |
| `zero_action` | Darwin-Arena-5 (previous run) | completed | 0.00 | Baseline from `REAL_ARENA_BENCHMARK_REPORT.md` |
| `heuristic_lift` | Darwin-Arena-5 (previous run) | completed | 0.00 | Open-loop delta sequence |

### Cheat policy evidence

`/tmp/rosclaw_data/arena_real/final_lift_cheat`:

```json
[
  {
    "task": "darwin_mvp_03_lift_object",
    "status": "completed",
    "success_rate": 1.0,
    "delta_success_rate": 0.0,
    "skill_discovery_rate": 1.0,
    "evolution_score": 0.0
  }
]
```

### Servo policy evidence

`/tmp/rosclaw_data/arena_real/final_lift_servo`:

```json
[
  {
    "task": "darwin_mvp_03_lift_object",
    "status": "completed",
    "success_rate": 0.0,
    "delta_success_rate": 0.0,
    "skill_discovery_rate": 0.0,
    "evolution_score": 0.0
  }
]
```

## What Changed in `HeuristicServoLiftPolicy`

1. **Reads the command target** from `observation["task_obs"][:3]` so the lift
   phase aims at the RL-task command target (same target used by `cheat_lift`).
2. **Detects controller mode** at runtime (`relative` vs. `absolute`) by
   inspecting `env.unwrapped.cfg.actions.arm_action`.
3. **Handles the 7-dim relative-pose action space** used by
   `DifferentialInverseKinematicsActionCfg`:
   - indices `0:3` = position delta in body frame,
   - indices `3:6` = orientation delta (axis-angle),
   - index `6` = gripper command.
4. **Maps world-frame deltas to the Franka panda_hand body frame** empirically:
   `body_x = -world_x`, `body_y = world_y`, `body_z = -world_z`.
5. **Skill hints** still adapt `kp`, `approach_offset_z`, `grasp_dist_threshold`,
   etc.

## Why Servo Did Not Yet Succeed

Container-side traces show the policy **does** drive the end-effector in the
right general directions:

- `x` increases from ~0.08 m toward the object at ~0.5 m.
- `z` decreases from ~0.84 m toward the object at ~0.055 m.

However, the effective Cartesian step size is very small (~1–2 mm per step),
because the `DifferentialIKController` is heavily damped and the `lift_object`
Arena environment uses a fixed `episode_length_s=5.0` (~100 steps). The arm
starts roughly 0.45 m away from the object and cannot close that distance
within the episode.

Attempts to increase the effective scale by overriding
`action_manager._terms["arm_action"]._scale` did not meaningfully increase the
step size, confirming that the limit is the joint-space response / physics
stepping rather than the commanded delta magnitude.

## Honest Conclusions

1. ✅ **The Arena eval pipeline can report non-zero success.** `cheat_lift`
   achieved `success_rate = 1.0` on real Docker rollouts, proving that task
   classification, registry matching, container launch, metric normalization,
   and summary generation all work end-to-end.
2. ❌ **`heuristic_servo_lift` is not yet a real capability baseline.** It
   makes observable progress but cannot complete `lift_object` within the
   default Arena episode length.
3. ⚠️ **The failure is a policy/controller limitation, not an infrastructure
   limitation.** With a faster controller, longer episode, or joint-space
   policy, the same observation-to-action loop should succeed.

## Recommendations / Next Steps

1. **Longer episode or evaluation-mode task** — switch the Arena task to an
   evaluation variant with a longer horizon, or lower the default
   `episode_length_s` used by `LiftObjectEnvironment`.
2. **Joint-space servo policy** — bypass the DifferentialIK damping by
   commanding target joint positions directly (requires reading current joint
   states from `observation["policy"]`).
3. **Learned policy** — load a pretrained RSL-RL / RoboTwin policy inside the
   container; this is the path originally intended by IsaacLab-Arena's
   `LiftObjectEnvironment`.
4. **Extend cheat baseline to other primitives** — implement `cheat_pick_place`,
   `cheat_close_door`, etc., as additional pipeline sanity checks.

## Artifacts

- Cheat summary: `/tmp/rosclaw_data/arena_real/final_lift_cheat`
- Servo summary: `/tmp/rosclaw_data/arena_real/final_lift_servo`
- Per-episode stderr logs: `/tmp/rosclaw_data/runs/arena_*.log`
- Updated policy file:
  `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- Updated adapter mapping: `rosclaw_darwin/adapters/arena.py`
- New configs:
  - `configs/policies/heuristic_servo_lift.yaml`
  - `configs/policies/heuristic_servo_lift_with_hints.yaml`
  - `configs/policies/cheat_lift.yaml`
- Tests: `tests/integration/test_arena_servo_policy.py`
