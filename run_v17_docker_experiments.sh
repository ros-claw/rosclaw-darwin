#!/usr/bin/env bash
set -e
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
LOG=logs/v17_docker_experiments.log
exec > "$LOG" 2>&1
echo "=== v1.7 Docker experiments started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "--- 1. Procedural object validity audit ---"
python scripts/diagnostics/run_procedural_object_validity_audit.py \
  --seeds 0:9 --audit-steps 11 --table-z 0.02 \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/diagnostics/procedural_object_validity_audit
echo "--- 2. Large-yaw slip diagnosis ---"
python scripts/diagnostics/run_large_yaw_slip_diagnosis.py \
  --seeds 0:19 --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/diagnostics/large_yaw_slip
echo "--- 3. Large-yaw targeted intervention ablation ---"
python scripts/ablations/run_large_yaw_intervention_ablation.py \
  --seeds 0:19 --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/ablations/large_yaw_intervention
echo "=== v1.7 Docker experiments finished $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
