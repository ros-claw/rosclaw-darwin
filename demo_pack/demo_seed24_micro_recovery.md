# Demo: Seed 24 micro-recovery

**Evidence card:** `seed24_micro_recovery`

**What it shows:**
- Baseline fails on seeds 24 and 198 due to post-lift slip.
- Candidate micro-recovery rescues both seeds without newly failing any baseline-success seeds.
- Promoted to `candidate_recovery` based on paired no-regression evidence.

**Run:**
```bash
darwin pair-eval \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --baseline configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --candidate configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml \
  --seeds 0:199 --out demo_outputs/pair_seed24 --mock

darwin promote \
  --candidate seed24_micro_recovery \
  --paired demo_outputs/pair_seed24/paired_summary.json \
  --out demo_outputs/promotions

darwin card --candidate seed24_micro_recovery --out demo_outputs/cards --mock

darwin registry add \
  --registry demo_outputs/registry \
  --name seed24_micro_recovery \
  --card demo_outputs/cards/seed24_micro_recovery.card.yaml
```

**Allowed claims:**
- Darwin can promote a candidate recovery based on paired no-regression evidence.

**Blocked claims:**
- Validated transferable skill is not claimed.
- Official 100/100 solved is not claimed.
