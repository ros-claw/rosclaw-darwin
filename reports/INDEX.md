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
- [Rotational Action Calibration Report](ROTATIONAL_ACTION_CALIBRATION_REPORT.md) — mapping action[3:6] to end-effector rotation (after sensor-reading fix).
- [Absolute Quaternion Calibration Report](ABSOLUTE_QUATERNION_CALIBRATION_REPORT.md) — absolute quaternion target produces controlled yaw (after sensor-reading fix).
- [Franka IK Orientation Investigation Report](FRANKA_IK_ORIENTATION_INVESTIGATION_REPORT.md) — deep dive into relative/absolute IK orientation failure.
- [Goal Pose Franka IK Abs Status Report](GOAL_POSE_FRANKA_IK_ABS_STATUS_REPORT.md) — current implementation status, 20-seed validation, and next steps for `franka_ik_abs`.
- [Dex-Cube Goal Pose Generalization Report](DEX_CUBE_GOAL_POSE_GENERALIZATION_REPORT.md) — 30-seed randomized validation of `franka_ik_abs` + v3 on the official `dex_cube` asset.
- [Dex-Cube Goal Pose 100-Seed Validation Report](DEX_CUBE_GOAL_POSE_100_SEED_VALIDATION_REPORT.md) — v1.6 clean 100-seed benchmark with failure classification, CI, and honest conclusions.
- [Reachability-Aware Approach Report](REACHABILITY_AWARE_APPROACH_REPORT.md) — side-pregrasp fix for positive-y / positive-yaw approach collisions.
- [Pre-Grasp Yaw Alignment v2 Report](PRE_GRASP_YAW_ALIGNMENT_V2_REPORT.md) — in-hand yaw-slip reduction experiments.
- [Goal Pose Grasp Stability Metrics v3 Report](GOAL_POSE_GRASP_STABILITY_METRICS_V3_REPORT.md) — object-following stability analysis of the latest goal_pose trace.
- [Goal Pose Physics Ablation Report](GOAL_POSE_PHYSICS_ABLATION_REPORT.md) — friction / size / mass diagnostic ablations.
- [Goal Pose Arena Asset Difference Report](GOAL_POSE_ARENA_ASSET_DIFFERENCE_REPORT.md) — Arena-side collision/contact differences between `dex_cube` and `procedural_cube`.
- [Goal Pose Object Geometry Adaptation Report](GOAL_POSE_OBJECT_GEOMETRY_ADAPTATION_REPORT.md) — `ObjectGeometryAdapter`: scaling grasp thresholds to the loaded object.
- [Goal Pose Subtask Decomposition Report](GOAL_POSE_SUBTASK_DECOMPOSITION_REPORT.md) — lift-only, lift-hold, and yaw subtask boundary.
- [Failure Signature v3 and Hint Recipe Report](FAILURE_SIGNATURE_V3_HINT_RECIPE_REPORT.md) — new signature tags and recipes.
- [Structural FailureToHint v3.1 Report](STRUCTURAL_FAILURE_TO_HINT_V31_REPORT.md) — regrasp / contact verify / lift verify strategy switches.
- [Cross-Task Transfer Status v2 Report](CROSS_TASK_TRANSFER_STATUS_V2_REPORT.md) — transfer level refresh.
- [Policy v3 Intervention Report](POLICY_V3_INTERVENTION_REPORT.md) — goal_pose policy v3: absolute-mode orientation, ObjectGeometryAdapter, verify_object_following, and official-asset success evidence.
- [Final Asset Fidelity Report](FINAL_ASSET_FIDELITY_REPORT.md) — separating official `dex_cube` benchmark results from procedural-cube fallback diagnostics.
- [External Goal Pose Review Package Report](EXTERNAL_GOAL_POSE_REVIEW_PACKAGE_REPORT.md) — packaged materials for external experts.
- [Final Goal Pose Diagnosis and Evolution Report](FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md) — answers to the 12 final questions.
- [Goal Pose Diagnostic Report for External Review](GOAL_POSE_DIAGNOSTIC_REPORT_FOR_EXTERNAL_REVIEW.md) — per-step trace diagnosis of why the cube slips, with questions for external experts.
- [Implementation Thoughts and Status Report](IMPLEMENTATION_THOUGHTS_AND_STATUS_REPORT.md) — first-person narrative of the v1.3/v1.4 follow-up implementation: thought process, problems, fixes, and honest conclusions.
- [V1.5 Follow-up Implementation Report](V1_5_FOLLOW_UP_IMPLEMENTATION_REPORT.md) — comprehensive summary of the v1.5 follow-up plan: P0 fixes, dex_cube generalization matrix, procedural gate audit, object-aware adaptation, FailureToHint v3 demo, and honest conclusions.
- [Procedural Contact Diagnosis Report](PROCEDURAL_CONTACT_DIAGNOSIS_REPORT.md) — contact-proxy classification for OOD fallback.
- [Procedural OOD Adaptive Recovery Report](PROCEDURAL_OOD_ADAPTIVE_RECOVERY_REPORT.md) — FBA-based adaptive recovery ablation.
- [Cross-Object / Cross-Yaw Generalization Report](CROSS_OBJECT_CROSS_YAW_GENERALIZATION_REPORT.md) — unified generalization matrix.
- [Final Darwin v1.6 Status Report](FINAL_DARWIN_V16_STATUS_REPORT.md) — Level A/B/C/D evidence summary.
- [Arena Issue Tracker](ARENA_ISSUE_TRACKER.md) — consolidated P0/P1/P2 questions for the IsaacLab-Arena team and simulation experts.

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
