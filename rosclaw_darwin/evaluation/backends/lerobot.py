"""LeRobot ``lerobot-eval`` evaluation backend.

This backend orchestrates the official LeRobot evaluation script in an isolated
runtime.  It never imports ``torch`` or ``lerobot`` at module load time; heavy
imports are deferred to the worker subprocess.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from rosclaw_darwin.evaluation.backends.base import (
    BackendProbe,
    EvaluationBackend,
    EvaluationPlan,
    RawEvaluationRun,
)
from rosclaw_darwin.evaluation.result import EvaluationResult


try:
    import pandas as pd
except Exception:  # pragma: no cover - pandas is a declared dependency
    pd = None  # type: ignore[assignment]


class LeRobotEvalBackend(EvaluationBackend):
    """Run LeRobot benchmark evaluations via the official ``lerobot-eval``."""

    name = "lerobot_eval"

    def __init__(self, default_runtime: dict[str, Any] | None = None) -> None:
        self._default_runtime = dict(default_runtime or {})

    # ------------------------------------------------------------------
    # Runtime resolution
    # ------------------------------------------------------------------
    def _resolve_runtime(self, spec: dict[str, Any]) -> dict[str, Any]:
        runtime = spec.get("runtime")
        if isinstance(runtime, dict):
            return {**self._default_runtime, **runtime}

        if isinstance(runtime, str):
            try:
                from rosclaw_darwin.evaluation.runtime import get_runtime

                registered = get_runtime(runtime)
                runtime = registered.model_dump(mode="json", exclude={"name"})
            except Exception:
                runtime = {}
        else:
            runtime = {}

        runtime_config = spec.get("runtime_config") or {}
        if isinstance(runtime_config, dict):
            runtime = {**runtime, **runtime_config}

        defaults = {
            **self._default_runtime,
            "python": shutil.which("python") or shutil.which("python3") or sys.executable,
            "lerobot_eval": shutil.which("lerobot-eval"),
        }
        return {**defaults, **runtime}

    @staticmethod
    def _probe_script_path() -> Path:
        return Path(__file__).resolve().parent.parent / "workers" / "lerobot_eval_probe.py"

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    def _build_env(self, spec: dict[str, Any], runtime: dict[str, Any]) -> dict[str, str]:
        env = dict(os.environ)
        runtime_env = runtime.get("environment")
        if isinstance(runtime_env, dict):
            env.update(runtime_env)

        allow_network = spec.get("policy", {}).get("allow_network", False)
        if allow_network:
            env.pop("HF_HUB_OFFLINE", None)
        else:
            env["HF_HUB_OFFLINE"] = "1"
        return env

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------
    def probe(self, spec: dict[str, Any]) -> BackendProbe:
        runtime = self._resolve_runtime(spec)
        python = runtime.get("python") or shutil.which("python3") or sys.executable
        request = {
            "policy_path": spec.get("policy", {}).get("path", ""),
            "env_type": spec.get("environment", {}).get("type", ""),
            "device": spec.get("policy", {}).get("device", "cpu"),
            "allow_network": spec.get("policy", {}).get("allow_network", False),
        }
        cmd = [
            str(python),
            str(self._probe_script_path()),
            "--request-json",
            json.dumps(request, sort_keys=True),
        ]
        env = self._build_env(spec, runtime)

        timeout_sec = int(
            spec.get("evaluation", {}).get("probe_timeout_sec", 60)
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout_sec,
                check=False,
            )
        except Exception as exc:
            return BackendProbe(
                status="error",
                messages=[f"probe launch failed: {exc}"],
                device={},
                policy={},
                environment={},
            )

        parsed = self._extract_json(proc.stdout)
        if parsed is None:
            return BackendProbe(
                status="error",
                messages=[
                    "probe returned non-JSON stdout: "
                    f"{proc.stdout!r} stderr: {proc.stderr!r}"
                ],
                device={},
                policy={},
                environment={},
            )

        status = parsed.get("status", "error")
        messages = parsed.get("messages", [])
        policy = parsed.get("policy", {})
        environment = parsed.get("environment", {})
        device = parsed.get("device", {})
        if "lerobot_version" in parsed:
            environment = {**environment, "lerobot_version": parsed["lerobot_version"]}
        if "torch_version" in parsed:
            environment = {**environment, "torch_version": parsed["torch_version"]}
        if "cuda" in parsed:
            device = {**device, "cuda": parsed["cuda"]}
        if "ffmpeg_available" in parsed:
            environment = {**environment, "ffmpeg_available": parsed["ffmpeg_available"]}
        if "benchmark_package" in parsed:
            environment = {**environment, "benchmark_package": parsed["benchmark_package"]}
        if "headless" in parsed:
            environment = {**environment, "headless": parsed["headless"]}
        if "compatibility" in parsed:
            environment = {**environment, "compatibility": parsed["compatibility"]}

        return BackendProbe(
            status=status,
            messages=messages,
            device=device,
            policy=policy,
            environment=environment,
        )

    @staticmethod
    def _extract_json(stdout: str) -> dict[str, Any] | None:
        start = stdout.find("{")
        if start == -1:
            return None
        depth = 0
        for i, ch in enumerate(stdout[start:]):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stdout[start : start + i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    def plan(self, spec: dict[str, Any]) -> EvaluationPlan:
        runtime = self._resolve_runtime(spec)
        spec_hash = self._hash_spec(spec)
        run_id = self._make_run_id()
        output_dir = self._output_dir(spec, run_id)

        policy = spec.get("policy", {})
        environment = spec.get("environment", {})
        benchmark = spec.get("benchmark", {})
        evaluation = spec.get("evaluation", {})

        command = self._build_command(
            policy=policy,
            environment=environment,
            evaluation=evaluation,
            output_dir=output_dir,
            runtime=runtime,
        )

        expected_tasks: list[str] = []
        task = environment.get("task")
        if task:
            expected_tasks.append(str(task))
        task_ids = environment.get("task_ids")
        if task_ids:
            expected_tasks.extend(str(t) for t in task_ids)

        expected_episodes = int(
            evaluation.get("n_episodes", environment.get("n_episodes", 0))
        )
        timeout_sec = int(evaluation.get("timeout_sec", 1800))

        return EvaluationPlan(
            run_id=run_id,
            spec_hash=spec_hash,
            backend=self.name,
            runtime=runtime,
            command=command,
            environment=environment,
            policy=policy,
            benchmark=benchmark,
            expected_tasks=expected_tasks,
            expected_episodes=expected_episodes,
            output_dir=str(output_dir),
            timeout_sec=timeout_sec,
        )

    @staticmethod
    def _hash_spec(spec: dict[str, Any]) -> str:
        canonical = json.dumps(spec, sort_keys=True, ensure_ascii=True, default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    @staticmethod
    def _make_run_id() -> str:
        return f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"

    @staticmethod
    def _output_dir(spec: dict[str, Any], run_id: str) -> Path:
        root = spec.get("output", {}).get("root", "data/eval_runs")
        return Path(root) / run_id

    def _build_command(
        self,
        policy: dict[str, Any],
        environment: dict[str, Any],
        evaluation: dict[str, Any],
        output_dir: Path,
        runtime: dict[str, Any],
    ) -> list[str]:
        args: list[str] = []

        exe = runtime.get("lerobot_eval")
        python = runtime.get("python") or shutil.which("python3") or sys.executable
        if exe:
            args.append(str(exe))
        else:
            args.extend([str(python), "-m", "lerobot.scripts.lerobot_eval"])

        if policy.get("path") is not None:
            args.append(f"--policy.path={policy['path']}")
        if environment.get("type") is not None:
            args.append(f"--env.type={environment['type']}")
        if environment.get("task") is not None:
            args.append(f"--env.task={environment['task']}")

        # ``batch_size`` lives in ``environment`` for EvaluationSpec, but callers
        # may also place it in ``evaluation`` for backward compatibility.
        batch_size = environment.get("batch_size") or evaluation.get("batch_size")
        if batch_size is not None:
            args.append(f"--eval.batch_size={batch_size}")
        if evaluation.get("n_episodes") is not None:
            args.append(f"--eval.n_episodes={evaluation['n_episodes']}")
        if evaluation.get("start_seed") is not None:
            args.append(f"--seed={evaluation['start_seed']}")
        if policy.get("device") is not None:
            args.append(f"--policy.device={policy['device']}")
        if policy.get("use_amp") is not None:
            args.append(f"--policy.use_amp={str(policy['use_amp']).lower()}")

        args.append(f"--output_dir={output_dir}")
        return args

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    def execute(self, plan: EvaluationPlan) -> RawEvaluationRun:
        root_dir, raw_dir = plan.ensure_output_dirs()
        stdout_path = raw_dir / "stdout.log"
        stderr_path = raw_dir / "stderr.log"
        eval_info_path = root_dir / "eval_info.json"
        command_path = raw_dir / "command.json"

        command_path.write_text(
            json.dumps(plan.command, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

        plan_path = root_dir / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "schema_version": "rosclaw.darwin.eval_plan.v1",
                    "run_id": plan.run_id,
                    "spec_hash": plan.spec_hash,
                    "backend": plan.backend,
                    "runtime": plan.runtime,
                    "command": plan.command,
                    "environment": plan.environment,
                    "policy": plan.policy,
                    "benchmark": plan.benchmark,
                    "expected_tasks": plan.expected_tasks,
                    "expected_episodes": plan.expected_episodes,
                    "output_dir": plan.output_dir,
                    "timeout_sec": plan.timeout_sec,
                },
                indent=2,
                ensure_ascii=True,
                default=str,
            ),
            encoding="utf-8",
        )

        provenance_dir = root_dir / "provenance"
        provenance_dir.mkdir(parents=True, exist_ok=True)
        for key in ("runtime", "policy", "environment", "benchmark", "command"):
            value = getattr(plan, key) if key != "command" else plan.command
            (provenance_dir / f"{key}.json").write_text(
                json.dumps(value, indent=2, ensure_ascii=True, default=str),
                encoding="utf-8",
            )

        env = self._build_env(
            {"policy": plan.policy},
            plan.runtime,
        )

        system_info = {
            "python_version": sys.version,
            "platform": platform.platform(),
            "HF_HUB_OFFLINE": env.get("HF_HUB_OFFLINE", "0"),
        }
        (provenance_dir / "system.json").write_text(
            json.dumps(system_info, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

        (root_dir / "artifacts" / "predicted_videos").mkdir(parents=True, exist_ok=True)

        returncode: int | None = None
        try:
            with (
                open(stdout_path, "w", encoding="utf-8") as stdout_f,
                open(stderr_path, "w", encoding="utf-8") as stderr_f,
            ):
                proc = subprocess.Popen(
                    plan.command,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    env=env,
                    start_new_session=True,
                )
                try:
                    returncode = proc.wait(timeout=plan.timeout_sec)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                    returncode = proc.returncode
        except Exception as exc:
            stderr_path.write_text(
                f"Darwin backend failed to launch command: {exc}",
                encoding="utf-8",
            )
            returncode = -1

        self._redact_file(stdout_path)
        self._redact_file(stderr_path)

        video_paths: list[str] = []
        videos_dir = root_dir / "artifacts" / "videos"
        if videos_dir.exists():
            video_paths = sorted(str(p) for p in videos_dir.rglob("*") if p.is_file())

        provenance = {
            "runtime": plan.runtime,
            "policy": plan.policy,
            "environment": plan.environment,
            "benchmark": plan.benchmark,
            "command": plan.command,
        }

        return RawEvaluationRun(
            run_id=plan.run_id,
            output_dir=str(root_dir),
            returncode=returncode,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            eval_info_path=str(eval_info_path),
            video_paths=video_paths,
            provenance=provenance,
        )

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------
    def normalize(
        self,
        raw_run: RawEvaluationRun,
        spec: dict[str, Any],
    ) -> EvaluationResult:
        from rosclaw_darwin.evaluation.gates import (
            PerformanceGate,
            ValidityGate,
            check_performance,
            check_validity,
        )
        from rosclaw_darwin.evaluation.parsers.lerobot_eval import (
            EvalInfoError,
            parse_eval_info,
        )
        from rosclaw_darwin.evaluation.result_v2 import EvaluationResultV2
        from rosclaw_darwin.evaluation.spec import EvaluationSpec
        from rosclaw_darwin.evaluation.statistics import (
            compute_task_statistics,
            macro_task_success_rate,
            micro_success_rate,
            smoke_sample_warning,
            wilson_ci,
        )

        try:
            eval_spec = spec if isinstance(spec, EvaluationSpec) else EvaluationSpec.model_validate(spec)
        except Exception:
            eval_spec = None

        output_dir = Path(raw_run.output_dir)
        normalized_dir = output_dir / "normalized"
        checks_dir = output_dir / "checks"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        checks_dir.mkdir(parents=True, exist_ok=True)

        parsed_info = None
        parse_error: dict[str, Any] | None = None
        try:
            expected = eval_spec.evaluation.n_episodes if eval_spec else None
            parsed_info = parse_eval_info(Path(raw_run.eval_info_path).parent, expected_episodes=expected)
        except EvalInfoError as exc:
            parse_error = {"code": exc.code.value, "message": exc.message}
        except Exception as exc:
            parse_error = {"code": "parse_exception", "message": str(exc)}

        raw_run_proxy = SimpleNamespace(exit_code=raw_run.returncode)
        validity: ValidityGate
        if eval_spec is not None:
            validity = check_validity(raw_run_proxy, parsed_info, eval_spec)
        else:
            validity = ValidityGate(status="unknown")

        policy = spec.get("policy", {})
        environment = spec.get("environment", {})

        metrics: dict[str, float] = {}
        raw_metrics: dict[str, Any] = {}
        confidence_intervals: dict[str, Any] = {}
        task_rows: list[dict[str, Any]] = []
        episode_rows: list[dict[str, Any]] = []
        task_results_path: str | None = None
        episode_results_path: str | None = None

        if parsed_info is not None:
            raw_metrics = {
                "lerobot.pc_success": parsed_info.pc_success,
                "lerobot.avg_sum_reward": parsed_info.avg_sum_reward,
                "lerobot.avg_max_reward": parsed_info.avg_max_reward,
                "lerobot.eval_s": parsed_info.eval_s,
                "lerobot.eval_ep_s": parsed_info.eval_ep_s,
            }
            if parsed_info.success_rate is not None and not math.isnan(parsed_info.success_rate):
                metrics["success_rate"] = parsed_info.success_rate
            if parsed_info.avg_sum_reward is not None and not math.isnan(parsed_info.avg_sum_reward):
                metrics["average_episode_reward"] = parsed_info.avg_sum_reward
            if parsed_info.avg_max_reward is not None and not math.isnan(parsed_info.avg_max_reward):
                metrics["average_max_reward"] = parsed_info.avg_max_reward
            if parsed_info.eval_s is not None and not math.isnan(parsed_info.eval_s):
                metrics["evaluation_seconds"] = parsed_info.eval_s
            if parsed_info.eval_ep_s is not None and not math.isnan(parsed_info.eval_ep_s):
                metrics["seconds_per_episode"] = parsed_info.eval_ep_s

            task_episodes = {
                task_id: list(task.episodes) for task_id, task in parsed_info.tasks.items()
            }
            task_stats = compute_task_statistics(task_episodes)

            for task_id, task in parsed_info.tasks.items():
                stats = task_stats[task_id]
                task_rows.append(
                    {
                        "run_id": raw_run.run_id,
                        "suite": task.suite,
                        "task_id": task_id,
                        "num_episodes": len(task.episodes),
                        "num_successes": sum(1 for ep in task.episodes if ep.success),
                        "success_rate": stats["success_rate"],
                        "success_ci_low": stats["success_ci_low"],
                        "success_ci_high": stats["success_ci_high"],
                        "avg_sum_reward": stats["avg_sum_reward"],
                        "avg_max_reward": stats["avg_max_reward"],
                        "eval_seconds": stats["eval_seconds"],
                        "status": "completed",
                    }
                )

            metrics["micro_success_rate"] = micro_success_rate(parsed_info.episodes)
            metrics["macro_task_success_rate"] = macro_task_success_rate(task_rows)

            n_total = len(parsed_info.episodes)
            n_success = sum(1 for ep in parsed_info.episodes if ep.success)
            ci_low, ci_high = wilson_ci(n_success, n_total)
            confidence_intervals["success_rate"] = {
                "confidence": 0.95,
                "low": ci_low,
                "high": ci_high,
                "method": "wilson",
            }
            confidence_intervals["task_success_rate"] = {
                row["task_id"]: {
                    "confidence": 0.95,
                    "low": row["success_ci_low"],
                    "high": row["success_ci_high"],
                    "method": "wilson",
                }
                for row in task_rows
            }

            for ep in parsed_info.episodes:
                episode_rows.append(
                    {
                        "run_id": raw_run.run_id,
                        "benchmark": environment.get("type"),
                        "suite": ep.suite,
                        "task_id": ep.task,
                        "episode_index": ep.episode_index,
                        "seed": ep.seed,
                        "success": ep.success,
                        "sum_reward": ep.sum_reward,
                        "max_reward": ep.max_reward,
                        "episode_steps": ep.steps,
                        "episode_seconds": None,
                        "terminated": ep.terminated,
                        "truncated": ep.truncated,
                        "video_path": ep.video_path,
                    }
                )

            task_results_path, episode_results_path = self._write_parquet_artifacts(
                normalized_dir,
                task_rows,
                episode_rows,
            )

            self._write_metric_definitions(normalized_dir)

        performance: PerformanceGate
        if eval_spec is not None:
            temp_result = EvaluationResultV2(
                run_id=raw_run.run_id,
                task_id=environment.get("type", ""),
                policy_id=policy.get("path", ""),
                adapter=self.name,
                status="completed",
                metrics=metrics,
                primary_metric="success_rate",
            )
            performance = check_performance(temp_result, eval_spec)
        else:
            performance = PerformanceGate(status="unknown", reason="no evaluation spec")

        if raw_run.returncode != 0:
            status = "backend_process_failed"
        elif validity.status != "passed":
            status = "invalid"
        else:
            status = "completed"

        benchmark_meta = {
            "backend": self.name,
            "env_type": environment.get("type"),
            "task": environment.get("task"),
            "task_ids": environment.get("task_ids"),
        }

        warning = smoke_sample_warning(len(parsed_info.episodes) if parsed_info else 0)

        result = EvaluationResultV2(
            run_id=raw_run.run_id,
            task_id=environment.get("type", ""),
            policy_id=policy.get("path", ""),
            adapter=self.name,
            status=status,
            benchmark=benchmark_meta,
            primary_metric="success_rate",
            metrics=metrics,
            raw_metrics=raw_metrics,
            metric_definitions=self._metric_definitions(),
            num_tasks=len(parsed_info.tasks) if parsed_info else None,
            num_episodes=len(parsed_info.episodes) if parsed_info else None,
            confidence_intervals=confidence_intervals,
            validity_gate={"status": validity.status, "checks": validity.checks},
            performance_gate={"status": performance.status, "reason": performance.reason},
            task_results_path=task_results_path,
            episode_results_path=episode_results_path,
            stdout_path=raw_run.stdout_path,
            stderr_path=raw_run.stderr_path,
            artifacts={
                "eval_info_path": raw_run.eval_info_path,
                "videos": raw_run.video_paths,
            },
            metadata={
                "returncode": raw_run.returncode,
                "parse_error": parse_error,
                "provenance": raw_run.provenance,
                "warning": warning,
            },
        )

        result_path = normalized_dir / "evaluation_result.json"
        result_path.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )

        (checks_dir / "validity_gate.json").write_text(
            json.dumps(
                {"status": validity.status, "checks": validity.checks},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        (checks_dir / "performance_gate.json").write_text(
            json.dumps(
                {"status": performance.status, "reason": performance.reason},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        hashes: dict[str, str] = {}
        for rel_path in (
            "plan.json",
            "eval_info.json",
            "normalized/evaluation_result.json",
        ):
            file_path = output_dir / rel_path
            if file_path.exists():
                hashes[rel_path] = hashlib.sha256(
                    file_path.read_bytes()
                ).hexdigest()
        hashes_path = output_dir / "hashes.json"
        hashes_path.write_text(
            json.dumps(hashes, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

        manifest = {
            "schema_version": "rosclaw.darwin.eval_manifest.v1",
            "run_id": raw_run.run_id,
            "backend": self.name,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plan_path": str(output_dir / "plan.json"),
            "provenance_dir": str(output_dir / "provenance"),
            "raw_dir": str(output_dir / "raw"),
            "normalized_dir": str(normalized_dir),
            "checks_dir": str(checks_dir),
            "hashes_path": str(hashes_path),
            "result_path": str(result_path),
        }
        (output_dir / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

        return result

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _redact_file(path: Path) -> None:
        """Redact sensitive tokens from a log file in-place."""
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8")
            redacted = LeRobotEvalBackend._redact_sensitive(text)
            path.write_text(redacted, encoding="utf-8")
        except Exception:  # pragma: no cover - best-effort redaction
            pass

    @staticmethod
    def _redact_sensitive(text: str) -> str:
        """Mask likely secret values in captured logs."""
        # Mask common credential patterns: KEY=VALUE, "key": "value", etc.
        pattern = re.compile(
            r"(?P<key>\b(?:HF_TOKEN|hf_token|HUGGINGFACE_TOKEN|API_KEY|api_key|"
            r"PASSWORD|password|SECRET|secret|TOKEN|token|PRIVATE_KEY)\b)"
            r"\s*[:=]\s*[^\s\"']+",
            re.IGNORECASE,
        )
        return pattern.sub(lambda m: f"{m.group('key')}=***", text)

    def _write_parquet_artifacts(
        self,
        normalized_dir: Path,
        task_rows: list[dict[str, Any]],
        episode_rows: list[dict[str, Any]],
    ) -> tuple[str | None, str | None]:
        if pd is None:
            return None, None

        task_path: str | None = None
        episode_path: str | None = None
        try:
            if task_rows:
                task_path = str(normalized_dir / "task_results.parquet")
                pd.DataFrame(task_rows).to_parquet(task_path, index=False)
            if episode_rows:
                episode_path = str(normalized_dir / "episode_results.parquet")
                pd.DataFrame(episode_rows).to_parquet(episode_path, index=False)
        except ImportError:
            # Parquet engine (pyarrow/fastparquet) is not installed; fall back to
            # JSON line artifacts so evidence is still queryable.
            if task_rows:
                task_path = str(normalized_dir / "task_results.jsonl")
                with open(task_path, "w", encoding="utf-8") as f:
                    for row in task_rows:
                        f.write(json.dumps(row, default=str) + "\n")
            if episode_rows:
                episode_path = str(normalized_dir / "episode_results.jsonl")
                with open(episode_path, "w", encoding="utf-8") as f:
                    for row in episode_rows:
                        f.write(json.dumps(row, default=str) + "\n")
        return task_path, episode_path

    def _write_metric_definitions(self, normalized_dir: Path) -> None:
        path = normalized_dir / "metric_definitions.json"
        path.write_text(
            json.dumps(self._metric_definitions(), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _metric_definitions() -> dict[str, Any]:
        return {
            "success_rate": {
                "description": "Proportion of successful episodes",
                "range": [0.0, 1.0],
                "source": "lerobot.pc_success / 100",
            },
            "micro_success_rate": {
                "description": "Pooled success rate across all episodes",
                "range": [0.0, 1.0],
                "source": "darwin.normalized",
            },
            "macro_task_success_rate": {
                "description": "Mean per-task success rate, tasks weighted equally",
                "range": [0.0, 1.0],
                "source": "darwin.normalized",
            },
            "average_episode_reward": {
                "description": "Mean sum_reward across episodes",
                "source": "lerobot.avg_sum_reward",
            },
            "average_max_reward": {
                "description": "Mean max_reward across episodes",
                "source": "lerobot.avg_max_reward",
            },
            "evaluation_seconds": {
                "description": "Total evaluation wall-clock time",
                "source": "lerobot.eval_s",
            },
            "seconds_per_episode": {
                "description": "Mean evaluation time per episode",
                "source": "lerobot.eval_ep_s",
            },
        }
