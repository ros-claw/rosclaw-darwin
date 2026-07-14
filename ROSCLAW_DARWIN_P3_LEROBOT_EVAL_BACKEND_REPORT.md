# ROSClaw-Darwin P3 — LeRobot Native Evaluation Backend Report

**Date:** 2026-07-13  
**Scope:** Implement the ROSClaw-Darwin P3 native evaluation backend that orchestrates the official `lerobot-eval` CLI, preserves raw evidence, normalizes metrics, computes statistics and confidence intervals, and separates validity gates from performance gates.

## 1. P2.2 baseline cleanup

P2.2 dataset-export and source-stream synchronization work is treated as the
baseline for this report (see memory: LeRobot P2.1 Gate B.1 done, P2 dataset
writer done).

Baseline cleanup completed in `rosclaw_repo/pyproject.toml`: the pytest
`addopts` plugin names for the ROS `launch_testing` / `launch_ros` plugins
used hyphens instead of the actual entry-point names (`launch_testing`,
`launch_ros`). When `PYTHONPATH` contained the Humble ROS Python paths,
those plugins were loaded, conflicted with the installed pytest version, and
prevented the core doctor/integration tests from collecting. The plugin names
were corrected to underscores so the core suite is now isolated from external
ROS runtime configuration.

Verification:

```bash
python -m pytest tests/test_doctor_*.py tests/integrations/test_lerobot_doctor*.py tests/integrations/test_lerobot_runtime*.py tests/integrations/test_lerobot_dataset_no_runtime.py -q
# 49 passed
```

For `rosclaw-darwin`, all evaluation unit tests continue to pass:

```bash
python -m pytest tests/unit/evaluation/ -q
# 54 passed, 1 warning
```

## 2. Runtime registry

Implemented a lightweight, file-backed registry at
`~/.rosclaw/darwin/eval_runtimes.yaml` (`rosclaw.darwin.eval_runtimes.v1`).

Files:

- `rosclaw_darwin/evaluation/runtime.py`
- `rosclaw_darwin/cli/eval_app.py` (`darwin eval runtime *`)

Commands:

```bash
darwin eval runtime list
darwin eval runtime register --name lerobot_default --mode external --python /venv/bin/python3
darwin eval runtime show lerobot_default
darwin eval runtime remove lerobot_default
```

The registry supports `external` Python runtimes and `docker` images, plus
per-runtime environment variables and tags. Each registered runtime can be
referenced from an `EvaluationSpec` by name.

## 3. EvaluationSpec

Implemented `rosclaw.darwin.eval_spec.v1` in
`rosclaw_darwin/evaluation/spec.py`.

Sections:

- `policy`: path, revision, device, use_amp, allow_network, overrides
- `environment`: type, task, task_ids, batch_size, max_parallel_tasks, use_async_envs, trust_remote_code
- `evaluation`: n_episodes, start_seed, timeout_sec, render_episodes, recording
- `output`: root, keep_raw, keep_videos, keep_worker_dir
- `validity_gates`: require_eval_info, require_expected_episode_count, require_all_tasks_completed, allow_nan_primary_metric
- `performance_gates`: minimum_success_rate, minimum_macro_task_success_rate

`runtime` may be a registered name (`str`) or an inline runtime dict.

Example specs:

- `configs/evals/pusht_diffusion_smoke.yaml`
- `configs/evals/pusht_diffusion_standard.yaml`
- `configs/evals/libero_spatial_smoke.yaml`

Benchmark registry:

- `configs/benchmarks/pusht.yaml`
- `configs/benchmarks/libero.yaml`
- `configs/benchmarks/metaworld.yaml`
- `configs/benchmarks/robomme.yaml`
- `configs/benchmarks/robotwin.yaml`
- `configs/benchmarks/isaaclab_arena.yaml`

## 4. LeRobot command plan

`LeRobotEvalBackend.plan()` builds a deterministic `rosclaw.darwin.eval_plan.v1`
with:

- SHA-256 spec hash
- Resolved runtime
- Full argv command list (no shell)
- Expected tasks and episodes
- Output directory and timeout

CLI:

```bash
darwin eval plan --spec configs/evals/pusht_diffusion_smoke.yaml
```

Command shape:

```text
lerobot-eval \
  --policy.path=lerobot/diffusion_pusht \
  --env.type=pusht \
  --eval.batch_size=2 \
  --eval.n_episodes=2 \
  --seed=42 \
  --policy.device=cuda \
  --policy.use_amp=false \
  --output_dir=data/eval_runs/eval_YYYYMMDD_HHMMSS_xxxx
```

The seed flag follows LeRobot 0.3.x (`--seed`) rather than 0.4.x (`--eval.seed`).
The backend automatically maps the spec field `evaluation.start_seed`.

## 5. Probe output

`rosclaw_darwin/evaluation/workers/lerobot_eval_probe.py` is executed inside
the target runtime. It reports:

- LeRobot version
- PyTorch / CUDA version and device name
- `lerobot-eval` CLI / module availability
- Policy path existence (local) and Hub repo existence (when network is allowed)
- Environment type registration status
- Requested device availability
- `ffmpeg` availability
- Benchmark package availability (e.g. `gym_pusht`)
- Headless rendering environment variables
- `compatibility`: `compatible | incompatible | unknown`
- Status: `ok | degraded | error`

CLI:

```bash
darwin eval doctor --runtime lerobot_default --spec configs/evals/pusht_diffusion_smoke.yaml
```

## 6. PushT real smoke

A real PushT smoke run was executed end-to-end with LeRobot 0.3.3 in an
isolated runtime (`/tmp/lerobot-runtime`). Because direct Hugging Face access
is blocked in this environment, the runtime is configured with
`HF_ENDPOINT=https://hf-mirror.com`.

Runtime registration:

```bash
python3 -m rosclaw_darwin.cli.main darwin eval runtime register \
  --name lerobot_default \
  --mode external \
  --python /tmp/lerobot-runtime/bin/python \
  --lerobot-eval /tmp/lerobot-runtime/bin/lerobot-eval \
  --env HF_ENDPOINT=https://hf-mirror.com \
  --tag pusht
```

Smoke execution:

```bash
python3 -m rosclaw_darwin.cli.main darwin eval doctor \
  --runtime lerobot_default --spec /tmp/pusht_smoke_writable.yaml
python3 -m rosclaw_darwin.cli.main darwin eval run \
  --spec /tmp/pusht_smoke_writable.yaml
python3 -m rosclaw_darwin.cli.main darwin eval validate \
  /tmp/eval_runs/eval_*
```

Result (mandatory 2-episode smoke):

```text
Status: completed
Validity gate: passed
Performance gate: passed
Success rate: 0.00%
```

A 2-episode sample is noisy for a stochastic policy/environment, so a longer
10-episode validation run was also executed:

```bash
python3 -m rosclaw_darwin.cli.main darwin eval run --spec /tmp/pusht_smoke_10ep.yaml
```

Result (10-episode validation):

```text
Status: completed
Validity gate: passed
Performance gate: passed
Success rate: 50.00%
Success-rate 95% CI: [23.66%, 76.34%]
```

Both runs satisfy all validity requirements and produce normalized metrics,
CIs, and artifact files. The 50% rate confirms the pretrained policy is
functional and the backend correctly measures success.

Real-smoke integration test:

```bash
HF_ENDPOINT=https://hf-mirror.com ROSCLAW_DARWIN_REAL_LEROBOT_EVAL=1 \
  python3 -m pytest tests/integration/test_real_lerobot_pusht.py -q
# 3 passed, 1 warning
```

## 7. Raw `eval_info.json` summary

The parser (`rosclaw_darwin/evaluation/parsers/lerobot_eval.py`) reads
`<output_dir>/eval_info.json` and preserves the full raw JSON. It supports:

- Flat single-task output
- LeRobot 0.3.x nested output with `aggregated` metrics and `per_episode`
  records
- LeRobot 0.4.x `tasks` dictionary
- `suites` / `groups` / `tasks` nesting
- Per-episode records with success, rewards, steps, termination, video paths,
  seed, and suite

Structured error codes:

- `eval_info_missing`
- `eval_info_invalid_json`
- `eval_schema_unsupported`
- `episode_count_mismatch`
- `task_result_missing`
- `metric_type_invalid`

## 8. Normalized metrics

`LeRobotEvalBackend.normalize()` produces Darwin-normalized metrics while
keeping LeRobot raw metrics:

| Darwin metric | Source |
|---|---|
| `success_rate` | `pc_success / 100.0` |
| `micro_success_rate` | pooled episodes |
| `macro_task_success_rate` | mean per-task rate |
| `average_episode_reward` | `avg_sum_reward` |
| `average_max_reward` | `avg_max_reward` |
| `evaluation_seconds` | `eval_s` |
| `seconds_per_episode` | `eval_ep_s` |

Raw metrics are preserved under `raw_metrics`:

- `lerobot.pc_success`
- `lerobot.avg_sum_reward`
- `lerobot.avg_max_reward`
- `lerobot.eval_s`
- `lerobot.eval_ep_s`

## 9. Episode and task results

For each run the backend writes:

- `normalized/task_results.parquet` (or `.jsonl` if no parquet engine is installed)
- `normalized/episode_results.parquet` (or `.jsonl`)
- `normalized/metric_definitions.json`

Task result columns: `run_id, suite, task_id, num_episodes, num_successes,
success_rate, success_ci_low, success_ci_high, avg_sum_reward, avg_max_reward,
eval_seconds, status`.

Episode result columns: `run_id, benchmark, suite, task_id, episode_index,
seed, success, sum_reward, max_reward, episode_steps, episode_seconds,
terminated, truncated, video_path`.

## 10. Wilson confidence intervals

`rosclaw_darwin/evaluation/statistics.py` implements:

- `wilson_ci(successes, n, confidence=0.95)`
- `micro_success_rate(episodes)`
- `macro_task_success_rate(tasks)`
- `compute_task_statistics(task_episodes)`
- `smoke_sample_warning(n_episodes)`

The overall success rate and per-task success rates receive Wilson 95%
confidence intervals. Edge cases (`n=0`, all-failure, all-success) are clamped.

## 11. Validity and performance gates

`rosclaw_darwin/evaluation/gates.py` separates the two gate families:

- **Validity gate**: process exit code, eval_info presence/parsability,
  expected episode count, primary-metric finiteness.
- **Performance gate**: `minimum_success_rate`,
  `minimum_macro_task_success_rate`.

A failed validity gate sets `status = invalid`; a failed performance gate
keeps `status = completed` but records `performance_gate.status = failed`.

Gate results are written to:

- `checks/validity_gate.json`
- `checks/performance_gate.json`

## 12. Artifacts and videos

Each run directory contains:

```text
data/eval_runs/<run_id>/
  manifest.yaml
  plan.json
  hashes.json
  provenance/
    runtime.json
    policy.json
    environment.json
    benchmark.json
    command.json
    system.json
  raw/
    command.json
    stdout.log
    stderr.log
  normalized/
    evaluation_result.json
    task_results.parquet|.jsonl
    episode_results.parquet|.jsonl
    metric_definitions.json
  checks/
    preflight.json
    validity_gate.json
    performance_gate.json
  artifacts/predicted_videos/   (collected when present)
```

Original `eval_info.json` is written at the run root by `lerobot-eval` and is
never overwritten by normalized artifacts.

Token redaction (`HF_TOKEN`, `api_key`, etc.) is applied before stdout/stderr
logs are persisted.

## 13. Core / LeRobot runtime test matrix

Unit tests:

```bash
python3 -m pytest tests/unit/evaluation/ -q
```

Result:

```text
69 passed, 1 warning
```

Key tests added or updated:

- `test_spec.py`, `test_runtime.py`
- `test_lerobot_backend_plan.py`
- `test_parser.py`, `test_statistics.py`, `test_gates.py`
- `test_normalize.py`
- `test_eval_cli.py`
- `test_evidence_layout.py`
- `test_core_imports.py`
- `test_fake_runner.py`

A fake `lerobot-eval` executable test verifies the full run/normalize/write
pipeline without requiring a real LeRobot installation. The optional real-smoke
integration test (`tests/integration/test_real_lerobot_pusht.py`) is gated by
`ROSCLAW_DARWIN_REAL_LEROBOT_EVAL=1`.

## 14. Optional benchmark probes

The backend and CLI are designed to support LIBERO, RoboMME, RoboTwin, and
IsaacLab-Arena through runtime tags and benchmark configs. A real runtime
probe for LIBERO or Arena requires the corresponding environment to be
installed and registered; P3 does not auto-install these dependencies.

Example benchmark configs are provided for all named benchmarks.

## 15. Known limitations

- Parquet output falls back to JSON lines when `pyarrow` or `fastparquet` is
  not installed in the runtime where `normalize()` runs.
- Multi-task benchmark aggregation is implemented; real multi-suite
  `eval_info.json` fixtures should be added in P3.1.
- Docker runtime execution is declared in the registry schema but not
  exercised in this session.

## 16. Next stage suggestions

1. **P3.1 Multi-benchmark compatibility**
   - Register real LeRobot runtimes for LIBERO, RoboMME, IsaacLab-Arena.
   - Execute and verify real smoke runs for each benchmark family.
   - Add parser fixtures for multi-suite `eval_info.json` outputs.

2. **P3.2 Paired comparison and robustness**
   - Extend `darwin eval compare` with paired-seed analysis and statistical
     tests.
   - Add mutation-robustness evaluation (baseline vs intervention).

3. **P4 Memory / How / Reward bridge**
   - Feed LeRobot evaluation recordings back into the Practice pipeline.
   - Add failure-conditioned evaluation and sandbox-controlled real robot
     rollout.

---

**Summary:** P3 delivers a complete native evaluation backend inside
`rosclaw-darwin`, with deterministic planning, subprocess execution, official
`eval_info.json` parsing, Darwin-normalized metrics, Wilson CIs, separated
gates, a `darwin eval` CLI, and a real LeRobot 0.3.3 PushT smoke run. All
unit tests pass (69 passed, 1 warning) and the optional real-smoke integration
test passes (3 passed, 1 warning).
