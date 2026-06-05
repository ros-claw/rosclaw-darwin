# Source Importers

## LW-BenchHub

`LWBenchHubImporter` scans YAML configs and Python gym registrations.

CLI:
```bash
darwin import lw --repo /data/repos/LW-BenchHub --out data/tasks/lw --limit 30
```

## RoboTwin

`RoboTwinImporter` scans `data/` directory for task folders with HDF5 demos and instructions.

CLI:
```bash
darwin import robotwin --repo /data/repos/RoboTwin --out data/tasks/robotwin --limit 20
```

## BEHAVIOR-1K

`Behavior1KImporter` performs semantic-only import of BDDL and activity definitions.

CLI:
```bash
darwin import behavior1k --repo /data/repos/BEHAVIOR-1K --semantic-only --out data/tasks/behavior1k --limit 100
```

All importers produce ROSClaw-TDL YAML with `metadata.executable=false` when the target simulator is not available.
