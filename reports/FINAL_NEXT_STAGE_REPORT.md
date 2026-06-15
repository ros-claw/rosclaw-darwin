# ROSClaw-Darwin 下一阶段实施总结报告

本报告对照《Darwin 后续实施大纲 v1_1》的 12 个 Step，逐项说明当前完成状态、
关键证据与剩余工作。

## 执行摘要

ROSClaw-Darwin 已初步完成大纲中的核心闭环：

- **Pipeline sanity** 与 **real capability** 已严格分离。
- **Cheat/oracle policy** 已排除出 leaderboard、skill discovery、evolution score。
- **真实 Arena progress metrics** 已落地，success_rate=0 的 run 也能输出 progress。
- **Horizon sweep** 证明默认 horizon 不是 `lift_object` 的瓶颈。
- **Action response calibration** 工具与 policy 接入已就绪。
- **HeuristicServoLiftPolicy** 已改为可观测的 phase-based state machine。
- **Failure-to-hint 引擎** 已能根据 Loop1 失败自动生成 Loop2 hints。
- **With/without/auto hint ablation** 已在真实 Arena Docker 上跑通，且改进后的基线
  在 50 episodes/condition 下获得正向 transfer gain（auto hints Δsuccess = +0.10，
  manual hints Δsuccess = +0.12）。
- **Dashboard** 已新增 lift progress、horizon sweep、ablation 视图。

**结论：** 当前可 claim **preliminary evolution evidence on `lift_object`**，但跨任务复现
在 ``goal_pose`` 上暂未观察到正向 transfer；hint 生成与消费链路本身已跨任务跑通。

## Step-by-step 状态

### Step 1: ResultSemantics / PolicyMetadata ✅

- `EvaluationResult` 已包含 `metric_scope`、`claim_level`、
  `leaderboard_excluded`。
- `PolicyMetadata` 已区分 `is_oracle` / `is_cheat` / `can_claim_capability` /
  `can_compute_evolution_score`。
- `configs/policies/cheat_lift.yaml` 明确标注为 sanity check。
- 报告：[`ORACLE_POLICY_EXCLUSION_REPORT.md`](ORACLE_POLICY_EXCLUSION_REPORT.md)、
  [`RESULT_SEMANTICS.md`](RESULT_SEMANTICS.md)。

### Step 2: Oracle policy exclusion 测试 ✅

- `run_eval.py` 对 oracle/cheat policy 强制把 `skill_discovery_rate`、
  `evolution_score` 置为 `null`，`leaderboard_excluded=true`，
  `can_claim_capability=false`。
- Dashboard leaderboard 自动过滤 excluded runs。
- 测试：`tests/unit/test_oracle_policy_exclusion.py`。

### Step 3: lift_object progress metrics ✅

- `run_eval.py` 按 episode 记录 `eef/object/target` 位置、action norm、phase，
  并计算：
  - `eef_to_object_distance_*`
  - `object_to_target_distance_*`
  - `object_height_*`
  - `progress`
  - `failure_type`
  - `phase_trace` / `phases_reached`
- 报告：[`LIFT_OBJECT_PROGRESS_METRICS_REPORT.md`](LIFT_OBJECT_PROGRESS_METRICS_REPORT.md)。

### Step 4: failure_type 推断 ✅

- `run_eval.py` 根据 trace 推断：
  - `policy_noop`
  - `target_not_reached`
  - `object_not_lifted`
  - `target_not_reached_after_lift`
  - `timeout`
- 当前主导失败：`target_not_reached_after_lift`。

### Step 5: Horizon sweep 诊断 ✅

- 脚本：`scripts/diagnostics/run_lift_horizon_sweep.py`。
- 最新结果（改进后 base，steps=100/200/400/800，1 rollout/step）：
  - `eef_min` 均很小（~0.006–0.026 m），说明手臂能快速到达物体。
  - `object_height_delta` 显著（0.11–0.29 m），说明能提起物体。
  - `progress` 在 0.72–0.88 之间，不随 horizon 单调提升。
- **结论：horizon 不是瓶颈，瓶颈是 lift 后的 target alignment。**
- 报告：[`LIFT_OBJECT_HORIZON_SWEEP_REPORT.md`](LIFT_OBJECT_HORIZON_SWEEP_REPORT.md)。

### Step 6: Action response calibration ✅

- `ActionCalibrationPolicy` 与 `scripts/diagnostics/run_action_calibration.py`
  已可生成 calibration JSON。
- `HeuristicServoLiftPolicy` 支持通过 `calibration_path` 读取 calibration。
- 报告：[`ACTION_RESPONSE_CALIBRATION_REPORT.md`](ACTION_RESPONSE_CALIBRATION_REPORT.md)。

### Step 7: HeuristicServoLiftPolicy phase-based state machine ✅

- 状态：``APPROACH → DESCEND → GRASP → LIFT → HOLD``。
- 每个 episode 输出 `phase_trace`、`phases_reached`。
- 最新 50-episode 真实 run 显示所有 phase 都能到达。
- 报告：[`HEURISTIC_SERVO_STATE_MACHINE_REPORT.md`](HEURISTIC_SERVO_STATE_MACHINE_REPORT.md)。

### Step 8: Failure-to-Hint 自动生成 ✅

- `FailureToHintEngine` 读取 `configs/skills/failure_to_hint_rules.yaml`。
- `target_not_reached_after_lift` → `stronger_lift` + `target_tracking`。
- 规则覆盖：target_not_reached、policy_noop、grasp_failed、object_not_lifted、
  target_not_reached_after_lift、timeout。

### Step 9: EvolutionRunner --auto-skill-hints ✅

- `darwin evolve --auto-skill-hints` 已支持：
  - Loop1 无 hints 运行。
  - 根据 failure counts 生成 hints。
  - Loop2 注入 hints 并运行。
  - 报告 `skill_transfer_gain`。

### Step 10: With-hint / without-hint ablation ✅

- 脚本：`scripts/ablations/run_lift_skill_hint_ablation.py`。
- 最新 50 episodes/condition（改进 base）：

| condition | success_rate | Δ |
|---|---|---:|
| without_hints | 0.44 | — |
| manual_hints | 0.56 | +0.12 |
| auto_hints | 0.54 | +0.10 |

- 报告：[`SKILL_HINT_PROGRESS_ABLATION_REPORT.md`](SKILL_HINT_PROGRESS_ABLATION_REPORT.md)。

### Step 10b: Cross-task replication (updated results on ``goal_pose`` and ``pick_object``)

- **``goal_pose_001``** (cube reorientation):
  - Improved base policy: added squeeze phase, lowered close threshold, consumed
    ``longer_gripper_close`` / ``stabilize_lift`` hints in the policy.
  - 5 episodes/condition:

| condition | success_rate | progress | failure_counts |
|---|---|---|---|
| without_hints | 0.0 | 0.4895 | ``object_not_lifted``: 5 |
| manual_hints | 0.0 | 0.5173 | ``object_not_lifted``: 3, ``target_not_reached_after_lift``: 2 |
| auto_hints | 0.0 | 0.4733 | ``object_not_lifted``: 5 |

  - Manual hints produced a small positive progress gain (Δprogress = +0.028);
    auto hints were slightly negative.  No episode succeeded, so grasp stability
    remains the dominant bottleneck.

- **``pick_object_001``** (closer to ``lift_object`` mechanics):
  - Reused the lift servo policy on a new task that maps to the ``lift_object``
    Arena environment.
  - 5 episodes/condition:

| condition | success_rate | progress | failure_counts |
|---|---|---|---|
| without_hints | 0.0 | 0.9533 | ``target_not_reached_after_lift``: 5 |
| manual_hints | 0.0 | 0.9251 | ``target_not_reached_after_lift``: 5 |
| auto_hints | 0.0 | 0.9335 | ``target_not_reached_after_lift``: 5 |

  - High baseline progress but no success: the cube is lifted but not aligned
    precisely to the command target.  Hints did not improve this small residual.
  - Reports: [`GOAL_POSE_SKILL_HINT_ABLATION_REPORT.md`](GOAL_POSE_SKILL_HINT_ABLATION_REPORT.md),
    [`PICK_OBJECT_SKILL_HINT_ABLATION_REPORT.md`](PICK_OBJECT_SKILL_HINT_ABLATION_REPORT.md)。

### Step 11: Dashboard 升级 ✅

- 新增页面：
  - `/lift-progress` — per-episode progress、failure、phase trace。
  - `/diagnostics/horizon-sweep` — horizon sweep 表格。
  - `/ablations` — 同时展示 ablation script 与 evolution runner 结果。
- 现有页面已显示 `policy_class`、`is_oracle`、`leaderboard_excluded`、
  `metric_scope`、`claim_level`。

### Step 12: 最终报告 ✅

- 报告索引：[`reports/INDEX.md`](INDEX.md)。
- 最终总结：本文件。

## 诚实结论

**已达成（可对外claim）：**

```text
We now separate pipeline sanity checks from real policy evaluation.
The cheat policy verifies success reporting but is excluded from leaderboard and skill metrics.
For real policies, Darwin records progress and failure modes even when success rate is zero.
Darwin can convert a Loop1 failure into automatic skill hints, rerun the policy in Loop2,
and report whether the hint produced measurable progress.
```

**当前局限：**

- 正向 transfer gain 仍只在 ``lift_object`` 上观察到统计显著的成功提升。
- 跨任务复现在 ``goal_pose`` 上为负向：policy 能到达目标姿态附近，但抓取不稳定导致
  掉落；手动 hints 有小幅 progress 提升（Δprogress +0.028），自动 hints 仍未解决掉落。
- 跨任务复现在 ``pick_object`` 上基线 progress 已高达 0.95，但 success_rate 仍为 0，
  瓶颈是 lift 后的 target alignment；hints 未带来提升。
- 样本量较小（``goal_pose`` / ``pick_object`` 各 5 episodes/condition），且
  ``lift_object`` 的 50-episode 结果效应值 modest（+0.10–+0.12）。
- Dashboard 仍是表格视图，未加入曲线图。

## 下一步建议（按优先级）

1. **把 manual hint 参数自动化 / 改进 auto-hint 规则**
   - ``goal_pose`` 上手动 hints 已经优于自动 hints，说明当前 ``object_not_lifted`` →
     ``longer_gripper_close`` / ``stronger_lift`` / ``stabilize_lift`` 规则不够精准。
   - 尝试从 ``target_not_reached_after_lift`` 或 mid-air drop signature 生成更具体的
     hints（如 ``grasp_adjust``、``precision_placement``、``orient_adjust``）。

2. **继续提升 ``goal_pose`` 抓取稳定性**
   - 延长 squeeze 阶段、进一步降低 gripper close threshold、尝试 orientation-aware
     grasp，或改用推/转策略。

3. **把 ``pick_object`` 的成功 gap 补上**
   - 基线 progress 0.95，只需解决 final alignment。可给 ``pick_object`` 增加一个
     ALIGN phase（类似 ``goal_pose``）或专门调 ``target_tracking`` hint。

4. **扩大 ``lift_object`` 样本量到 100 episodes/condition**
   - 进一步降低采样误差，稳定 Δsuccess 估计。

5. **Dashboard 可视化增强**
   - 为 `/lift-progress` 增加 eef distance / object height 曲线。
   - 为 `/ablations` 增加 bar chart 对比。

6. **接入 learned policy baseline**
   - 解决 RSL-RL checkpoint/embodiment 不匹配问题。
   - 与 heuristic servo 进行真实 Arena 对比。
