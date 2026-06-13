# Arena Capability Matching Report

**Date:** 2026-06-13  
**Registry:** `configs/arena/capability_registry.yaml`  
**Matcher:** `rosclaw_darwin.arena_bridge.task_matcher.TaskArenaMatcher`  

## 1. Registry Environment List

| Environment | Backend | Scene Domains | Supported Primitives | Required Primitives | Horizon |
|---|---|---|---|---|---|
| `lift_object` | arena | tabletop, default | pick, lift | (none) | atomic |
| `kitchen_pick_and_place` | arena | kitchen | pick, place | pick, place | short |
| `franka_put_and_close_door` | arena | kitchen | pick, place, close | place, close | composite |
| `tabletop_sort_cubes` | arena | tabletop, packing_table | sort, pick, place | sort | short |
| `press_button` | arena | tabletop, packing_table | press | press | atomic |
| `cube_goal_pose` | arena | tabletop | orient, rotate | (none) | atomic |

## 2. Task-to-Environment Matches

| Task | Best Env | Score | Matched Primitives | Missing Required | Warnings |
|---|---|---|---|---|---|
| `darwin_mvp_03_lift_object` | `lift_object` | 0.712 | lift | — | — |
| `darwin_kitchen_pick_and_place_cube` | `kitchen_pick_and_place` | 0.850 | pick, place | — | — |
| `darwin_mvp_21_put_object_in_microwave_and_close_door` | `franka_put_and_close_door` | 0.780 | close, pick, place | — | — |
| `lw_snacksorting` | `lift_object` (fallback) | 0.0 | — | — | matched by legacy fallback; native_env_name override will select `SnackSorting` at runtime |
| `lw_shakershuffle` | `lift_object` (fallback) | 0.0 | — | — | matched by legacy fallback; native_env_name override will select `ShakerShuffle` at runtime |

## 3. Failed Matches

Tasks that do not match any registry environment with `score >= 0.5` fall back to the legacy hard-coded mapper in `ArenaAdapter._map_primitives_to_arena_env`. This fallback is intentionally retained during the transition period.

Examples:
- LW-BenchHub tasks imported from Python classes with no primitives/objects rely on `provenance.native_env_name` and are currently matched to `lift_object` fallback, then corrected at runtime by `native_config`.
- Tasks with entirely unknown primitives (e.g., `navigate`, `wave`) still fall back to `lift_object`.

## 4. Hard-Coded Mapping Removed Status

- ❌ Not fully removed. `ArenaAdapter._map_primitives_to_arena_env` now calls `_map_task_to_arena_env(task, robot)` first.
- ✅ The declarative `TaskArenaMatcher` is the primary decision path.
- ✅ If the matcher returns a strong executable match, the legacy if-else chain is skipped.
- ⚠️ Legacy fallback remains for tasks whose provenance does not yet expose enough primitives/objects to score in the registry.

## 5. CLI Verification

```bash
darwin arena-match --task examples/tasks/native/put_object_in_microwave_and_close_door.yaml
```

Output:

```text
Best match for darwin_mvp_21_put_object_in_microwave_and_close_door:
franka_put_and_close_door
  score: 0.78
  native_env_name: franka_put_and_close_door
  matched_primitives: close, pick, place
  arena_args: {'environment': 'franka_put_and_close_door', 'object': 'dex_cube', 'embodiment': 'franka_ik'}
```

## 6. Conclusion

The Arena Capability Registry and `TaskArenaMatcher` now provide a transparent, scored mapping from ROSClaw tasks to Arena environments. Native tasks with complete primitives/objects map correctly. Importers that produce sparse primitives/objects require either registry entries for their native environments or richer primitive inference before the legacy fallback can be fully removed.
