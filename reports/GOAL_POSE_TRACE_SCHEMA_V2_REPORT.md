# Goal Pose Trace Schema v2 Report

## 1. Purpose

The original goal_pose trace recorded a single field called `orientation_error`,
which was actually the **object yaw error to the target yaw**.  Because the
object was not grasped during the `PRE_GRASP_ORIENT` phase, its yaw naturally
stayed constant.  The previous report incorrectly concluded from this that the
gripper yaw controller was unresponsive.

Trace schema v2 separates end-effector orientation from object orientation so
that physical diagnosis can answer:

1. Does the commanded rotational action actually rotate the end-effector?
2. Does the end-effector yaw align with the object / target yaw?
3. Does the object yaw follow the end-effector yaw once grasped?
4. Which rotational action axis controls yaw in relative mode?

---

## 2. New trace fields

| Field | Meaning |
|---|---|
| `eef_qx`, `eef_qy`, `eef_qz`, `eef_qw` | End-effector quaternion (raw) |
| `eef_roll` | End-effector roll angle |
| `eef_pitch` | End-effector pitch angle |
| `eef_yaw` | End-effector yaw angle |
| `desired_eef_yaw` | Yaw the policy wants the end-effector to hold |
| `eef_yaw_error` | `desired_eef_yaw - eef_yaw` (wrapped to \[-π, π\]) |
| `object_yaw` | Object world-frame yaw |
| `target_yaw` | Target pose yaw |
| `object_yaw_error` | `target_yaw - object_yaw` (renamed from `orientation_error`) |
| `action_rot_x` | `action[..., 3]` rotational command |
| `action_rot_y` | `action[..., 4]` rotational command |
| `action_rot_z` | `action[..., 5]` rotational command |
| `phase` | Current policy state |

`orientation_error` is kept as a deprecated alias for `object_yaw_error` so
that existing parsers do not break, but all new analysis should use
`object_yaw_error`.

---

## 3. Trace metadata

A sidecar file `trace_metadata.json` is written next to `episode_trace.jsonl`:

```json
{
  "trace_schema_version": "goal_pose_trace_v2",
  "orientation_error_definition": "object_yaw_error_to_target_yaw",
  "eef_yaw_recorded": true
}
```

This makes the semantic definition of each field explicit and versioned.

---

## 4. Code changes

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
  - Added `_write_trace_metadata` helper.
  - `HeuristicServoGoalPosePolicy.__init__` writes schema metadata.
  - Trace append block now records eef rpy/quat, desired/eef yaw error,
    object yaw error, and rotational action components.
  - Added `_quat_to_rpy` helper consistent with the existing `_quat_to_yaw`
    convention used in the policy.

- `reports/GOAL_POSE_GRASP_STABILITY_REPORT.md`
  - Added diagnostic correction noting that the previous
    `PRE_GRASP_ORIENT` conclusion confused object yaw with end-effector yaw.

- `tests/unit/test_goal_pose_trace_schema.py`
  - Verifies metadata, field presence, and quaternion-to-RPY correctness.

- `tests/integration/test_goal_pose_trace_orientation_fields.py`
  - Runs the policy against a scene-backed mock environment and checks that
    every trace step contains the v2 orientation fields.

---

## 5. Tests

```bash
ruff check rosclaw_darwin tests
pytest tests/unit/test_goal_pose_trace_schema.py \
       tests/integration/test_goal_pose_trace_orientation_fields.py -q
```

Result: **8 passed**.

Full suite:

```bash
pytest tests/unit tests/integration -q \
  -p no:launch_testing -p no:launch_ros \
  -p no:ament_pep257 -p no:ament_lint -p no:ament_copyright \
  -p no:ament_flake8 -p no:ament_xmllint
```

Result: **153 passed**.

---

## 6. Corrected conclusion

> The previous trace recorded **object yaw error**, not end-effector yaw error.
> Since the object was not grasped during `PRE_GRASP_ORIENT`, object yaw was
> expected to remain unchanged.  End-effector yaw logging and rotational action
> calibration are required before concluding whether the yaw action channel
> works.

---

## 7. Next step: rotational action calibration

With schema v2 in place, the next sprint will:

1. Command pure `action[..., 3]`, `action[..., 4]`, `action[..., 5]` signals
   in free space.
2. Record the resulting `eef_roll`, `eef_pitch`, `eef_yaw` deltas.
3. Identify which action axis controls yaw in `franka_ik` relative mode.
4. Repeat with the object grasped to check whether object yaw follows eef yaw.

This calibration is the prerequisite for any targeted policy v3 intervention.
