# ROSClaw-Darwin Reports Index

## Result semantics and infrastructure

- [Result Semantics](RESULT_SEMANTICS.md) — how to interpret mock, real, and evolution results.
- [Oracle Policy Exclusion Report](ORACLE_POLICY_EXCLUSION_REPORT.md) — ``cheat_lift`` is excluded from leaderboard and skill metrics.

## Reproducibility and statistics

- [Reproducibility and Statistics Foundation Report](REPRODUCIBILITY_AND_STATISTICS_FOUNDATION_REPORT.md) — metadata, seed, CI, and significance-test foundation.
- [Lift Object Statistical Validation Report](LIFT_OBJECT_STATISTICAL_VALIDATION_REPORT.md) — multi-seed ablation with CIs and Fisher exact tests.

## Real Arena baseline and diagnostics

- [Lift Object Progress Metrics Report](LIFT_OBJECT_PROGRESS_METRICS_REPORT.md) — real progress evidence for ``heuristic_servo_lift``.
- [Lift Object Horizon Sweep Report](LIFT_OBJECT_HORIZON_SWEEP_REPORT.md) — horizon sweep diagnosis.
- [Action Response Calibration Report](ACTION_RESPONSE_CALIBRATION_REPORT.md) — action-axis to world displacement calibration.
- [Heuristic Servo State Machine Report](HEURISTIC_SERVO_STATE_MACHINE_REPORT.md) — phase traces and state-machine behaviour.
- [Real Arena Baseline Improvement Report](REAL_ARENA_BASELINE_IMPROVEMENT_REPORT.md) — servo success breakthrough and with/without-hint matrix.
- [Learned Lift Baseline Report](LEARNED_LIFT_BASELINE_REPORT.md) — pretrained RSL-RL checkpoint results and blockers.

## Pick / place and goal pose

- [Pick Object Success Gap Report](PICK_OBJECT_SUCCESS_GAP_REPORT.md) — why progress ≈ 0.95 but success = 0, and the ALIGN/HOLD intervention.
- [Goal Pose Grasp Stability Report](GOAL_POSE_GRASP_STABILITY_REPORT.md) — grasp instability diagnosis and squeeze/stabilize intervention.
- [Goal Pose Trace Schema v2 Report](GOAL_POSE_TRACE_SCHEMA_V2_REPORT.md) — separating end-effector yaw from object yaw for physical diagnosis.
- [Gripper Calibration Report](GRIPPER_CALIBRATION_REPORT.md) — empty vs. cube-blocked gripper closure limits.
- [Rotational Action Calibration Report](ROTATIONAL_ACTION_CALIBRATION_REPORT.md) — mapping action[3:6] to end-effector rotation.
- [Goal Pose Diagnostic Report for External Review](GOAL_POSE_DIAGNOSTIC_REPORT_FOR_EXTERNAL_REVIEW.md) — per-step trace diagnosis of why the cube slips, with questions for external experts.

## Evolution and ablation

- [Skill Hint Progress Ablation Report](SKILL_HINT_PROGRESS_ABLATION_REPORT.md) — with/without/auto hint comparison and transfer gain.
- [Failure Signature v2 Report](FAILURE_SIGNATURE_V2_REPORT.md) — fine-grained failure signatures and tag rules.
- [Hint Rules v2 Report](HINT_RULES_V2_REPORT.md) — signature-driven recipes, conflict resolution, and manual-hint mining.
- [Goal Pose Skill Hint Ablation Report](GOAL_POSE_SKILL_HINT_ABLATION_REPORT.md) — cross-task replication on `goal_pose` (cube reorientation).
- [Pick Object Skill Hint Ablation Report](PICK_OBJECT_SKILL_HINT_ABLATION_REPORT.md) — cross-task replication on `pick_object`.
- [Real Arena Evolution Evidence Report](REAL_ARENA_EVOLUTION_EVIDENCE_REPORT.md) — large-N follow-up of the closed-loop failure-to-hint pipeline.
- [Final Next Stage Report](FINAL_NEXT_STAGE_REPORT.md) — step-by-step status against the implementation outline and remaining work.

## Cross-task and final status

- [Cross-Task Transfer Summary Report](CROSS_TASK_TRANSFER_SUMMARY_REPORT.md) — transfer levels across lift_object / pick_object / goal_pose.
- [Dashboard Evolution Evidence Report](DASHBOARD_EVOLUTION_EVIDENCE_REPORT.md) — visualization plan and anti-misleading principles.
- [Learned Policy Baseline Integration Report](LEARNED_POLICY_BASELINE_INTEGRATION_REPORT.md) — RSL-RL baseline wiring and blockers.
- [Final Evolution Benchmark Status Report](FINAL_EVOLUTION_BENCHMARK_STATUS_REPORT.md) — answers to the 12 final questions.

## Historical

- [Real Arena Benchmark Report](REAL_ARENA_BENCHMARK_REPORT.md) — original Darwin-Arena-5 baseline.
