# Goal Pose Physics Ablation Report

## 1. Purpose

Determine whether goal_pose failure is caused by contact/friction properties of
the fallback procedural cube, or by policy/controller factors.

All variants use the same `cube_goal_pose` environment and the same
`heuristic_servo_goal_pose` policy with manual grasp-stability hints.  These
are **diagnostic** ablations, not official benchmark results.

---

## 2. Method

The ROSClaw adapter was extended to accept a `physics_ablation` metadata block
in the task YAML.  It patches the procedural cube's spawn configuration before
the IsaacLab stage is built:

- `static_friction` / `dynamic_friction`
- `size`
- `mass`

Command:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_physics_ablation.py \
  --out-dir /tmp/rosclaw_data/physics_ablation
```

Variants:

| variant | change |
|---|---|
| baseline | procedural cube defaults (0.2 kg, 5x10x10 cm, friction 0.5) |
| high_friction | friction 2.5 (5x baseline) |
| small_cube | size 2.5x5x5 cm (half linear dimensions) |
| light_cube | mass 0.1 kg (half baseline) |

Result file: `/tmp/rosclaw_data/physics_ablation/physics_ablation_1781515386.json`

---

## 3. Results

| variant | object_lifted | object_peak | min yaw_error | drop_detected | grasp_stability_score |
|---|---|---:|---:|---:|---:|
| baseline | true | 0.327 | 0.493 | true | 0.65 |
| high_friction | true | 0.329 | 0.686 | true | 0.65 |
| small_cube | true | 0.332 | 0.594 | true | 0.65 |
| light_cube | true | 0.331 | 0.621 | true | 0.65 |

All variants successfully lifted the cube to ~0.33 m.  None achieved the target
yaw (min error remained far above the 0.2 rad tolerance).  Drops occurred in
all cases.

---

## 4. Interpretation

| hypothesis | supported? |
|---|---|
| Low friction causes slip/drop | Not strongly.  High friction did not improve yaw alignment or prevent drop. |
| Cube too large for gripper | Not strongly.  Smaller cube did not improve yaw alignment or prevent drop. |
| Cube too heavy for grip force | Not strongly.  Lighter cube did not improve yaw alignment or prevent drop. |
| Policy/controller yaw authority is the bottleneck | **Yes.**  All physics variants lifted, but none could actively reorient the cube. |

The passive object yaw observed in every trace is caused by the cube slipping
inside the gripper, not by controlled end-effector rotation.  Because the
rotational action channel has zero authority (see Rotational Action Calibration
Report), changing physics parameters cannot solve the reorientation failure.

---

## 5. Fallback asset note

The `cube_goal_pose` environment requests `dex_cube`, but the Docker runtime
falls back to the local `procedural_cube` because Nucleus-backed assets are not
available.  The fallback cube has known parameters (0.2 kg, 5x10x10 cm,
friction 0.5).  These ablations therefore test the **fallback variant**, not
the official Arena `dex_cube`.

---

## 6. Answers to outline questions

1. **Does friction affect success/drop?** No clear effect in this fallback variant.
2. **Does cube size affect gripper closure/drop?** No clear effect.
3. **Does cube mass affect lift stability?** No clear effect.
4. **Does fallback procedural cube pollute benchmark?** It changes the object
   geometry and physics relative to the intended `dex_cube`; results should be
   labeled as `goal_pose_procedural_variant`.
5. **Is this official Arena task or modified variant?** Modified variant due to
   procedural fallback and diagnostic physics overrides.

---

## 7. Conclusion

Physics ablation does **not** point to friction, size, or mass as the primary
failure cause.  The failure boundary remains the inability to command
end-effector yaw.  This is a controller/embodiment issue, not a material issue.
