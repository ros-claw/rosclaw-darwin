# Task Execution Classification Report

**Date:** 2026-06-13  
**Metric scope:** `infrastructure`  
**Claim level:** `infrastructure`  

## 1. ExecutionSpec Schema

`ExecutionSpec` has been added to `rosclaw_darwin/tdl/schema.py`:

```python
class ExecutionSpec(BaseModel):
    executable: bool = False
    backend: ExecutionBackend | str = ExecutionBackend.unknown
    mode: ExecutionMode | str = ExecutionMode.unknown
    requires_gpu: bool = False
    requires_docker: bool = False
    semantic_only: bool = False
    reason: str | None = None
    native_env_name: str | None = None
    adapter: str | None = None
    metadata: dict = Field(default_factory=dict)
```

Backends: `arena`, `robotwin_replay`, `behavior_semantic`, `mock`, `native`, `unknown`.  
Modes: `live`, `docker`, `subprocess`, `replay`, `semantic_only`, `mock`, `unknown`.

## 2. Importer Behavior

| Source | Default `backend` | Default `mode` | `executable` | `semantic_only` |
|---|---|---|---|---|
| LW-BenchHub | `arena` | `docker` | `true` | `false` |
| RoboTwin | `robotwin_replay` | `replay` | `true` | `false` |
| BEHAVIOR-1K | `behavior_semantic` | `semantic_only` | `false` | `true` |

## 3. Imported Task Counts

| Source | Count | Executable | Semantic-only |
|---|---|---|---|
| LW-BenchHub | 5 | 5 | 0 |
| RoboTwin | 5 | 5 (replay) | 0 |
| BEHAVIOR-1K | 10 | 0 | 10 |
| Native Arena tasks | 3 | 3 | 0 |
| Native mutated variant | 1 | 1 | 0 |
| **Total** | **24** | **14** | **10** |

Native Arena tasks:
- `examples/tasks/native/lift_object.yaml`
- `examples/tasks/native/kitchen_pick_and_place.yaml`
- `examples/tasks/native/put_object_in_microwave_and_close_door.yaml`

## 4. Suite Filtering Validation

Commands:

```bash
darwin suite create --tasks "/tmp/darwin_imported/**/*.yaml" \
  --filter "execution.executable=true" --out /tmp/executable_suite.yaml
# Result: 15 executable tasks

darwin suite create --tasks "/tmp/darwin_imported/**/*.yaml" \
  --filter "execution.semantic_only=true" --out /tmp/semantic_suite.yaml
# Result: 10 semantic-only tasks

darwin suite create --tasks "/tmp/darwin_imported/**/*.yaml" \
  --filter "execution.backend=arena" --out /tmp/arena_suite.yaml
# Result: 5 arena tasks
```

Verification:
- `executable_suite.yaml` contains no `execution.executable=false` tasks.
- `semantic_suite.yaml` contains only BEHAVIOR-1K tasks.
- `arena_suite.yaml` contains only LW-BenchHub tasks.
- Mixed suites print a warning: "Warning: N semantic-only tasks are excluded from execution metrics."

## 5. Excluded Tasks and Reasons

- BEHAVIOR-1K tasks are imported as `semantic_only` because they come from a task ontology (BDDL) without a corresponding IsaacLab-Arena scene instantiation.
- RoboTwin tasks are `executable` but under `robotwin_replay` because the current importer only maps them to replay artifacts, not live Arena control.

## 6. Conclusion

Task execution classification is now first-class in the TDL schema and importer pipeline. Suites can be filtered by `execution.executable`, `execution.backend`, and `execution.semantic_only`, preventing semantic-only tasks from being mixed into real success-rate averages.
