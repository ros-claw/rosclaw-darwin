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
