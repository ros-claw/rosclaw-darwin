#!/usr/bin/env bash
set -e

OUTDIR="demo_outputs"
mkdir -p "$OUTDIR"

echo "=== 1. Validate official dex_cube environment ==="
darwin validate-env \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --out "$OUTDIR/validity_official" \
  --mock

echo "=== 2. Run paired no-regression evaluation ==="
darwin pair-eval \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --baseline configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --candidate configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml \
  --seeds 0:4 \
  --out "$OUTDIR/pair_seed24" \
  --mock

echo "=== 3. Generate seed24 evidence card ==="
darwin card \
  --candidate seed24_micro_recovery \
  --out "$OUTDIR/cards" \
  --mock

echo "=== 4. Register promoted recovery ==="
darwin registry add \
  --registry "$OUTDIR/registry" \
  --name seed24_micro_recovery \
  --card "$OUTDIR/cards/seed24_micro_recovery.card.yaml"

echo "=== 5. Bundle report ==="
darwin report \
  --out "$OUTDIR/report" \
  --cards "$OUTDIR/cards"

echo "=== Demo complete. Outputs in $OUTDIR ==="
