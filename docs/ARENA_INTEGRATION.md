# IsaacLab-Arena Integration

## Three Integration Modes

### Mode A: Native Arena Pass-through (P0)
TDL stores `provenance.native_config` and runs Arena's `policy_runner.py` directly.

### Mode B: External Environment Class (P1)
Darwin-native tasks use `DarwinExternalEnvironment` inheriting from Arena's external environment interface.

### Mode C: TDL-to-Arena Compiler (P2)
Full compilation from TDL scene/embodiment/objects/primitives to Arena components.

## Current Adapter

`ArenaAdapter` in `rosclaw_darwin/adapters/arena.py` preserves the deep integration from prior work:
- Monkey-patches for Warp, IsaacLab compatibility
- Procedural cube fallbacks when Nucleus is unavailable
- Franka IK/Joint embodiment mapping
- Contact sensor patches for procedural objects

## v1.7 Official GR1 Open Microwave Workflow

Darwin v1.7 adds an orchestration layer for the official NVIDIA Arena GR1 Open Microwave learned-policy workflow:

- **Route:** `nvidia/Arena-GR1-Manipulation-Task` @ `arena_v0.2_lab_v3.0` → `nvidia/GN1x-Tuned-Arena-GR1-Manipulation` @ `gn1_6` → `GR00T_N1_6` on `gr1_open_microwave`.
- **Adapter:** `rosclaw_darwin/adapters/arena_official_runner_adapter.py`
- **CLI:** `darwin arena official run`
- **Configs:** `configs/tasks/arena/gr1_open_microwave_official.yaml`, `configs/policies/arena_gr1_gn1x_official.yaml`
- **Gate:** `configs/release/darwin_v17_arena_official_gate.yaml` + `scripts/quality/run_darwin_v17_arena_official_gate.py`
- **Repro package:** `release/darwin_v1_7_arena_official_repro/`

The adapter does not re-implement the policy; it runs the published Sprint scripts inside the Arena Docker container and converts their stdout/stderr/metrics into Darwin `RunArtifact`, `EvidenceCard`, `Registry`, and `Dashboard` entries.  If a runtime stage fails (e.g., Hugging Face download timeout), the adapter emits an honest blocked report rather than fabricating metrics.
