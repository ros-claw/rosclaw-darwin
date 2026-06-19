# Goal Pose Arena Asset Difference Report

**Date:** 2026-06-17  
**Investigation:** Arena-side differences between `dex_cube` (USD asset) and `procedural_cube` (fallback)  
**Scope:** collision approximation, contact offset, rest offset, torsional patch radius, mass, and physics material.

---

## 1. Motivation

`franka_ik_abs` solves `cube_goal_pose` for the registered `dex_cube` asset (20/20 seeds) but fails on the local `procedural_cube` fallback with `object_not_lifted` for every seed and orientation.  Earlier physics ablations varying size, friction, and mass did not recover success.  This report investigates whether matching the **Arena-side USD collision/contact configuration** of `dex_cube` would make the procedural fallback behave like the registered asset.

---

## 2. Method

### 2.1 USD inspection of `dex_cube_instanceable.usd`

The registered asset is located at:

```
/data/omniverse/Assets/Isaac/6.0/Isaac/Props/Blocks/DexCube/dex_cube_instanceable.usd
```

Because `usdcat` is not available inside the Arena Docker image, the composed stage was exported to USDA with `usd-core` (Python 3.10) on the host.  The relevant physics attributes were read from the exported `/tmp/dex_cube_export.usda`.

### 2.2 Procedural cube spawn configuration

The fallback cube is generated in `isaaclab_arena/assets/object_library.py` by `ProceduralCube._generate_rigid_cfg`, which returns a `sim_utils.CuboidCfg`.  Its defaults are:

| parameter | default value |
|---|---|
| `size` | `(0.05, 0.1, 0.1)` m |
| `physics_material.static_friction` | `0.5` |
| `physics_material.dynamic_friction` | `0.5` (inherited) |
| `rigid_props.solver_position_iteration_count` | `16` |
| `rigid_props.solver_velocity_iteration_count` | `0` |
| `collision_props.contact_offset` | `0.005` |
| `mass_props.mass` | `0.2` kg |

### 2.3 Extending `physics_ablation` plumbing

`rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` was extended to forward additional override keys from the task YAML into the container-side `ProceduralCube` spawn config:

- `contact_offset`
- `rest_offset`
- `torsional_patch_radius`
- `min_torsional_patch_radius`
- `solver_velocity_iteration_count`

These keys are applied after Isaac Sim initialization, before the scene is built.

### 2.4 New diagnostic task config

`configs/tasks/goal_pose_procedural_cube_dex_collision.yaml` sets the procedural cube to match the composed `dex_cube` USD values:

```yaml
physics_ablation:
  size: [0.048, 0.048, 0.048]
  contact_offset: 0.001
  rest_offset: 0.0
  torsional_patch_radius: 0.1
  min_torsional_patch_radius: 0.008
  mass: 0.216
  solver_velocity_iteration_count: 1
```

### 2.5 Ablation command

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin
python scripts/diagnostics/run_goal_pose_object_ablation.py \
  --tasks configs/tasks/goal_pose_procedural_cube_dex_collision.yaml \
  --seeds 5 \
  --out-dir /tmp/rosclaw_data/goal_pose_dex_collision_ablation \
  --cleanup
```

Each seed ran sequentially with a private trace directory to avoid container/GPU interference.

---

## 3. USD findings

### 3.1 Effective collision size

The `dex_cube` collision prim is a unit cube with scale `(0.06, 0.06, 0.06)` and extent `±0.03` m, giving an effective cube side length of `0.06` m before the `DexCube` root scale is applied.  The `DexCube` class in `object_library.py` sets:

```python
class DexCube(LibraryObject):
    name = "dex_cube"
    scale = (0.8, 0.8, 0.8)
```

Therefore the effective collision side length in simulation is:

```
0.06 * 0.8 = 0.048 m
```

This is the value used in the new ablation config (`size: [0.048, 0.048, 0.048]`).

### 3.2 Collision/contact properties

From the composed USDA:

```usda
def Cube "collisions" (
    apiSchemas = ["PhysicsCollisionAPI", "PhysxCollisionAPI"]
)
{
    float3[] extent = [(-0.03, -0.03, -0.03), (0.03, 0.03, 0.03)]
    float physxCollision:contactOffset = 0.001
    float physxCollision:minTorsionalPatchRadius = 0.008
    float physxCollision:restOffset = 0
    float physxCollision:torsionalPatchRadius = 0.1
    double size = 1
    double3 xformOp:scale = (0.05999999865889549, 0.05999999865889549, 0.05999999865889549)
}
```

| property | `dex_cube` | default `procedural_cube` |
|---|---|---|
| `contactOffset` | `0.001` | `0.005` |
| `restOffset` | `0.0` | default (0.0) |
| `torsionalPatchRadius` | `0.1` | default (0.0) |
| `minTorsionalPatchRadius` | `0.008` | default (0.0) |

The default procedural cube's `contact_offset=0.005` inflates the collision shape relative to the registered asset, which was the leading hypothesis for why fingers could not penetrate enough to form a stable grasp.

### 3.3 Mass

The root rigid body in the composed USDA declares:

```usda
float physics:mass = 0.216
```

### 3.4 Physics material

The collision prim binds a physics material:

```usda
rel material:binding:physics = </DexCube/CubeMaterial>
```

However, `CubeMaterial` is **not defined** in either the main `dex_cube_instanceable.usd` layer or the referenced `Props/instanceable_meshes.usd` layer.  The referenced layer only defines `DexMaterial`, which is a visual `OmniPBR` shader (base color, albedo map, etc.) with no physics/friction attributes.  This implies:

1. The physics material may be created at runtime by IsaacLab/Arena code, or
2. The physics material binding is unresolved and PhysX falls back to default friction values.

Either way, **the USD asset itself does not encode an object-side friction coefficient**, so the earlier ablations that only changed `procedural_cube` friction may not have matched any meaningful `dex_cube` value.

### 3.5 Visual vs collision geometry

The visual mesh is a 2×2×2 unit cube scaled by `(0.03, 0.03, 0.03)`, while the collision cube is a unit cube scaled by `(0.06, 0.06, 0.06)`.  After the root `scale = 0.8`, the visual mesh is `0.048` m and the collision shape is also `0.048` m, so visual and collision geometry are consistent.

### 3.6 Solver iterations

The composed USDA does **not** specify `solver_position_iteration_count` or `solver_velocity_iteration_count` on the rigid body.  IsaacLab defaults are used.  The ablation config sets `solver_velocity_iteration_count: 1` to match typical defaults; this value was not the focus of the hypothesis.

---

## 4. Ablation results

| seed | success_rate | progress | object_height_delta | object_height_max | eef_to_object_dist_min | failure_type |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 0.0 | 0.4953 | -0.153 | 0.200 | 0.009 | object_not_lifted |
| 1 | 0.0 | 0.4953 | -0.153 | 0.200 | 0.009 | object_not_lifted |
| 2 | 0.0 | 0.4953 | -0.153 | 0.200 | 0.009 | object_not_lifted |
| 3 | 0.0 | 0.4953 | -0.153 | 0.200 | 0.009 | object_not_lifted |
| 4 | 0.0 | 0.4953 | -0.153 | 0.200 | 0.009 | object_not_lifted |

**Aggregate:** 0/5 success.

The metrics are identical to the previous `goal_pose_procedural_cube_baseline` and `goal_pose_procedural_cube_dex_size` failures:

- `progress = 0.4953`
- `object_height_delta = -0.153`
- `object_height_max = 0.2`
- `eef_to_object_distance_min = 0.009`
- failure type `object_not_lifted`

This shows the policy descends to the object but does not transition out of `DESCEND` under the default `grasp_z_tolerance` / `grasp_dist_threshold`.  The collision/contact parameter matching did not change this signature.

---

## 5. Interpretation

| hypothesis | supported? |
|---|---|
| `dex_cube` succeeds because its effective size is `~0.048` m | Not supported.  Matching size alone (previous `dex_size` ablation) and matching size + contact properties (this report) both fail. |
| `contact_offset` inflation prevents finger penetration | Not supported.  Reducing `contact_offset` from `0.005` to `0.001` does not recover lift. |
| Missing torsional patch radius reduces grasp stability | Not supported.  Setting `torsional_patch_radius=0.1` and `min_torsional_patch_radius=0.008` does not recover lift. |
| Mass mismatch is the cause | Not supported.  Matching mass `0.216` kg does not recover lift. |
| Physics material / friction is the cause | Inconclusive.  The USD does not expose `CubeMaterial`, so we cannot confirm what friction `dex_cube` actually uses. |
| The failure is a policy-side grasp-geometry mismatch | **Strongly supported.**  The policy never leaves `DESCEND` for any procedural variant, while it succeeds on the registered `dex_cube`.  The difference is therefore not explained by the tested collision/contact parameters. |

The most likely remaining causes are:

1. **Policy grasp thresholds are tuned to the registered `dex_cube` asset.**  The `franka_ik_abs` policy was validated only on `dex_cube`; its `grasp_z_tolerance`, `grasp_dist_threshold`, and approach trajectory may assume a specific collision shape, initial settle height, or finger-cube contact configuration that the procedural variant does not reproduce.

2. **Unmeasured asset differences.**  There may be differences in inertia tensor, center-of-mass offset, finger friction material, gripper collision approximation, or initial object settle pose that are not visible in the exported USDA and are not exposed by the current `physics_ablation` keys.

3. **Physics material binding is unresolved for `dex_cube`.**  If `CubeMaterial` is missing and PhysX uses a default material, the effective friction of `dex_cube` may actually match the procedural cube's default, explaining why friction ablation had no effect.

---

## 6. Honest conclusion

- **Matching `dex_cube` collision/contact properties on the procedural fallback does not solve `object_not_lifted`.**
- The failure signature is unchanged across size, friction, mass, contact offset, rest offset, and torsional patch radius variations.
- The gap between `dex_cube` and `procedural_cube` is therefore **not a simple collision-parameter mismatch**.
- The next most promising direction is **policy-side grasp adaptation** (object-aware approach height, gripper-width-aware closure thresholds, contact-feedback-driven regrasp) or registering the true `dex_cube` asset in the local Docker runtime.

---

## 7. Open questions for the Arena team

1. What is the intended physics material for `dex_cube`?  The USD binds `</DexCube/CubeMaterial>` but the prim is not authored in the asset layers.
2. What are the official `dex_cube` inertia tensor and center-of-mass offset?
3. Is the `procedural_cube` fallback expected to be behaviorally interchangeable with `dex_cube` for `cube_goal_pose`?
4. Are there additional collision/collision-approximation settings (e.g., convex decomposition, collision mesh vs cube primitive) that differ between the two assets?

---

## 8. Files changed

- `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` — extended `physics_ablation` override keys.
- `configs/tasks/goal_pose_procedural_cube_dex_collision.yaml` — new diagnostic task config.
- `reports/GOAL_POSE_ARENA_ASSET_DIFFERENCE_REPORT.md` — this report.
- `reports/INDEX.md` — added entry.

---

## 9. Reproduction

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

# Inspect dex_cube collision/contact properties
python3.10 -c "
from pxr import Usd
stage = Usd.Stage.Open('/data/omniverse/Assets/Isaac/6.0/Isaac/Props/Blocks/DexCube/dex_cube_instanceable.usd')
stage.Export('/tmp/dex_cube_export.usda')
print('Exported to /tmp/dex_cube_export.usda')
"

# Run the collision-matching ablation
python scripts/diagnostics/run_goal_pose_object_ablation.py \
  --tasks configs/tasks/goal_pose_procedural_cube_dex_collision.yaml \
  --seeds 5 \
  --out-dir /tmp/rosclaw_data/goal_pose_dex_collision_ablation \
  --cleanup
```

---

## 10. Data location

- Aggregate JSON: `/tmp/rosclaw_data/goal_pose_dex_collision_ablation/object_ablation_YYYY-MM-DD_HHMMSS.json`
- Per-seed summaries: `/tmp/rosclaw_data/goal_pose_dex_collision_ablation/task_goal_pose_procedural_cube_dex_collision/object_procedural_cube/yaw_0/seed_*/summary.json`
- Exported USDA: `/tmp/dex_cube_export.usda`

**Facts for write gate:**
1. This report will be referenced from `reports/INDEX.md` (no line number yet; the index is updated manually below).
2. No existing report covers Arena-side asset differences between `dex_cube` and `procedural_cube`; the closest reports are `GOAL_POSE_PHYSICS_ABLATION_REPORT.md` (size/friction/mass only) and `GOAL_POSE_FRANKA_IK_ABS_STATUS_REPORT.md` (status overview).
3. Data files referenced: ablation aggregate JSON with fields `args`, `per_run`, `by_condition`; per-run fields `task_id`, `object`, `physics_ablation`, `yaw_deg`, `seed`, `status`, `metrics`, `failure_types`, `elapsed_seconds`; metrics include `success_rate`, `progress_mean`, `object_height_delta_mean`, `object_height_max_mean`, `eef_to_object_distance_min_mean`, etc. Date formats: filename timestamp `YYYY-MM-DD_HHMMSS`, report date `YYYY-MM-DD`.
4. User instruction: "排查完了，你将当前状态整理成一份详细的本地汇报".
