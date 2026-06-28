"""ArenaRunner: subprocess / Docker wrapper for IsaacLab-Arena execution."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.utils.logging import setup_logger

logger = setup_logger(__name__)

DEPS_DIR = Path(__file__).parent / "arena_docker_deps"


class ArenaRunner:
    """Run Arena evaluation jobs via subprocess or Docker."""

    def __init__(
        self,
        arena_repo: Path | None = None,
        python_bin: str | None = None,
        mode: str = "auto",
        docker_image: str = "rosclaw-darwin:arena-base",
    ):
        self.arena_repo = Path(arena_repo) if arena_repo else None
        self.python_bin = python_bin or self._find_isaac_python() or "python"
        self.mode = mode
        self.docker_image = docker_image

    @staticmethod
    def _find_isaac_python() -> str | None:
        """Look for Isaac Sim bundled python."""
        isaac_root = os.environ.get("ISAACSIM_PATH") or os.environ.get("ISAAC_PATH")
        if isaac_root:
            p = Path(isaac_root) / "kit" / "python" / "bin" / "python3"
            if p.exists():
                return str(p)
        for candidate in [
            "/data/omniverse/pkg/isaac-sim-5.1.0/kit/python/bin/python3",
            "/usr/share/isaac-sim/kit/python/bin/python3",
        ]:
            if Path(candidate).exists():
                return candidate
        return None

    def _use_docker(self) -> bool:
        if self.mode == "docker":
            return True
        if self.mode == "subprocess":
            return False
        # auto: use docker if arena_repo is missing or local Isaac Sim not found
        if self.arena_repo is None or not self.arena_repo.exists():
            return True
        if self.python_bin == "python":
            return True
        return False

    def run_policy_runner(
        self,
        job: dict[str, Any],
        task_id: str,
        policy_id: str,
    ) -> EvaluationResult:
        """Run Arena eval_runner via subprocess or Docker."""
        run_id = f"arena_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if self._use_docker():
            return self._run_docker(job, run_id, task_id, policy_id, started_at)
        return self._run_subprocess(job, run_id, task_id, policy_id, started_at)

    def _run_subprocess(
        self,
        job: dict[str, Any],
        run_id: str,
        task_id: str,
        policy_id: str,
        started_at: str,
    ) -> EvaluationResult:
        cmd = self._build_command(job)
        logger.info(f"Running Arena (subprocess): {' '.join(cmd)}")

        env = os.environ.copy()
        for key in ("PYTHONPATH", "LD_LIBRARY_PATH", "ISAAC_PATH", "CARB_APP_PATH"):
            if key in os.environ:
                env[key] = os.environ[key]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=job.get("timeout_seconds", 600),
                cwd=str(self.arena_repo) if self.arena_repo else None,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return self._make_error_result(
                run_id, task_id, policy_id, cmd, exc.stdout or "", exc.stderr or "", -1, started_at
            )
        except FileNotFoundError as exc:
            return self._make_error_result(
                run_id, task_id, policy_id, cmd, "", str(exc), -1, started_at
            )

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        metrics = self._parse_stdout(proc.stdout)
        return EvaluationResult(
            run_id=run_id,
            task_id=task_id,
            policy_id=policy_id,
            adapter="arena",
            status="completed" if proc.returncode == 0 else "failed",
            metrics=metrics,
            command=cmd,
            stdout_path=None,
            stderr_path=None,
            started_at=started_at,
            finished_at=finished_at,
            metadata={
                "return_code": proc.returncode,
                "stdout_preview": proc.stdout[:2000],
                "stderr_preview": proc.stderr[:2000],
            },
        )

    @staticmethod
    def _detect_infrastructure_failure(stderr: str) -> tuple[bool, list[str]]:
        """Return True if stderr contains a non-policy infrastructure error.

        These signals indicate Docker / Isaac Sim / HDF5 / filesystem problems
        rather than policy behaviour, so the run must not be counted as a policy
        outcome.
        """
        if not stderr:
            return False, []
        patterns = {
            "blocking_io_error": re.compile(r"BlockingIOError", re.IGNORECASE),
            "python_traceback": re.compile(r"Traceback \(most recent call last\)"),
            "hdf5_lock_error": re.compile(r"unable to lock file", re.IGNORECASE),
            "h5py_error": re.compile(r"\bh5py\.", re.IGNORECASE),
            "cuda_oom": re.compile(r"CUDA out of memory", re.IGNORECASE),
            "no_space_left": re.compile(r"No space left on device", re.IGNORECASE),
        }
        signals = [name for name, pat in patterns.items() if pat.search(stderr)]
        return bool(signals), signals

    @staticmethod
    def _pick_gpu_device() -> str:
        """Select the GPU with the most free memory, falling back to 'all'."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                return "all"
            best = "all"
            best_free = -1.0
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",") if p.strip()]
                if len(parts) != 2:
                    continue
                idx, free = parts
                free_mb = float(free)
                if free_mb > best_free:
                    best_free = free_mb
                    best = idx
            return best
        except Exception:
            return "all"

    def _run_docker(
        self,
        job: dict[str, Any],
        run_id: str,
        task_id: str,
        policy_id: str,
        started_at: str,
    ) -> EvaluationResult:
        """Run Arena inside Docker container with stubs/patches."""
        with tempfile.TemporaryDirectory(prefix="rosclaw_arena_") as tmpdir:
            tmp_path = Path(tmpdir)
            # Write eval job config
            eval_config = {"jobs": [job]}
            config_path = tmp_path / "eval_jobs.json"
            config_path.write_text(json.dumps(eval_config, indent=2))

            # Create metrics output file (shared with container via bind mount)
            metrics_path = tmp_path / "metrics_output.json"
            metrics_path.write_text("{}")

            # Per-run trace directory: prevents concurrent containers from racing on
            # the shared episode_trace.jsonl file. The host directory is supplied by
            # the caller (e.g. run_goal_pose_trace.py) and bind-mounted into the
            # container at the location the policy/run_eval expect.
            trace_dir = job.get("_trace_dir")
            if trace_dir:
                trace_path = Path(trace_dir)
                trace_path.mkdir(parents=True, exist_ok=True)
                trace_mount_src = str(trace_path)
            else:
                trace_mount_src = "/tmp/rosclaw_data/traces"

            # Build docker run command
            site_packages = "/isaac-sim/kit/python/lib/python3.12/site-packages"
            gpu_arg = os.environ.get("ROSCLAW_ARENA_GPU_DEVICES", self._pick_gpu_device())
            cmd = [
                "docker", "run", "--rm", "--gpus", f"device={gpu_arg}" if gpu_arg != "all" else "all",
                "-e", "ACCEPT_EULA=Y",
                "-e", "DISPLAY=",
                "-e", "OPENBLAS_NUM_THREADS=1",
                "-e", "OMP_NUM_THREADS=1",
                "-e", "HDF5_USE_FILE_LOCKING=FALSE",
                "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-e", "ROSCLAW_TRACE_DIR=/workspace/data/traces",
            ]
            # Forward seed/placement_seed from the job into the container so the
            # environment builder can vary initial conditions consistently.
            if job.get("seed") is not None:
                cmd.extend(["-e", f"ROSCLAW_ARENA_SEED={job['seed']}"])
            if job.get("placement_seed") is not None:
                cmd.extend(["-e", f"ROSCLAW_ARENA_PLACEMENT_SEED={job['placement_seed']}"])

            # Mount optional route-classifier model so the container can load it.
            policy_cfg = job.get("policy_config_dict") or {}
            route_classifier_path = policy_cfg.get("route_classifier_path")
            if route_classifier_path:
                rc_host = Path(route_classifier_path).resolve()
                if rc_host.exists():
                    cmd.extend(["-v", f"{rc_host}:{rc_host}"])
                else:
                    logger.warning(
                        "route_classifier_path references a missing file: %s", rc_host
                    )

            # Mount optional learned residual / trigger model weights so the
            # container-side heuristic policy can load them at the same
            # host-absolute paths used in the YAML config.
            for model_key in ("residual_policy_path", "trigger_model_path"):
                model_path = policy_cfg.get(model_key)
                if model_path:
                    model_host = Path(model_path).resolve()
                    if model_host.exists():
                        cmd.extend(["-v", f"{model_host}:{model_host}"])
                    else:
                        logger.warning(
                            "%s references a missing file: %s", model_key, model_host
                        )

            # If the job uses a learned residual policy, the container needs the
            # host learning modules (rosclaw_darwin.learning.*) because the
            # rosclaw_darwin package is not installed inside Docker.  Build a
            # temporary package overlay and mount it into /workspace/data so
            # run_eval.py's sys.path insertion makes the imports resolve.
            if policy_cfg.get("residual_policy") not in (None, "none", ""):
                overlay_root = tmp_path / "rosclaw_darwin"
                overlay_learning = overlay_root / "learning"
                overlay_learning.mkdir(parents=True, exist_ok=True)
                (overlay_root / "__init__.py").write_text("")
                (overlay_learning / "__init__.py").write_text("")
                learning_src = Path(__file__).resolve().parent.parent / "learning"
                for module_name in (
                    "residual_policy.py",
                    "bounded_residual_policy.py",
                    "trigger_model.py",
                ):
                    src = learning_src / module_name
                    if src.exists():
                        (overlay_learning / module_name).write_bytes(src.read_bytes())
                    else:
                        logger.warning("Learning overlay missing source: %s", src)
                cmd.extend(["-v", f"{overlay_root}:/workspace/data/rosclaw_darwin"])

            cmd.extend([
                "--entrypoint", "",
                # Mount eval config
                "-v", f"{config_path}:/workspace/data/eval_jobs.json",
                # Mount metrics output file
                "-v", f"{metrics_path}:/workspace/data/metrics_output.json",
                # Mount asset root (host local assets -> container)
                "-v", "/data/omniverse/Assets/Isaac/6.0:/data/omniverse/Assets/Isaac/6.0",
                "-v", "/data/omniverse/Assets/Isaac/5.1:/data/omniverse/Assets/Isaac/5.1",
                # Overlay the missing Arena assets from 6.0 onto the 5.1 tree
                # without modifying the shared host directory.
                "-v", "/tmp/rosclaw_arena_51_overlay/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab/Arena:/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab/Arena",
                # Mount kit patches (local asset root instead of HTTPS)
                "-v", f"{DEPS_DIR / 'isaaclab.python.kit'}:/workspace/submodules/IsaacLab/apps/isaaclab.python.kit",
                "-v", f"{DEPS_DIR / 'isaaclab.python.headless.kit'}:/workspace/submodules/IsaacLab/apps/isaaclab.python.headless.kit",
                # Mount stubs
                "-v", f"{DEPS_DIR / 'isaaclab_teleop'}:{site_packages}/isaaclab_teleop",
                "-v", f"{DEPS_DIR / 'isaaclab_newton'}:{site_packages}/isaaclab_newton",
                "-v", f"{DEPS_DIR / 'isaaclab_physx'}:{site_packages}/isaaclab_physx",
                # Mount patches
                "-v", f"{DEPS_DIR / 'kuka_allegro.py'}:/workspace/isaaclab_arena/embodiments/kuka_allegro/kuka_allegro.py",
                "-v", f"{DEPS_DIR / 'isaaclab_arena_manager_based_env.py'}:/workspace/isaaclab_arena/environments/isaaclab_arena_manager_based_env.py",
                "-v", f"{DEPS_DIR / 'visual_materials.py'}:/workspace/submodules/IsaacLab/source/isaaclab/isaaclab/sim/spawners/materials/visual_materials.py",
                # Mount permissive object_reference patch (allows non-Z-axis
                # parent rotations in kitchen_pick_and_place etc.).
                "-v", f"{DEPS_DIR / 'object_reference.py'}:/workspace/isaaclab_arena/assets/object_reference.py",
                # Mount XformPrimView patch (standardizes Mesh/Scope prims from 6.0 assets).
                "-v", f"{DEPS_DIR / 'xform_prim_view.py'}:/workspace/submodules/IsaacLab/source/isaaclab/isaaclab/sim/views/xform_prim_view.py",
                # Mount absolute-pose IK embodiment patch (adds franka_ik_abs).
                "-v", f"{DEPS_DIR / 'franka_ik_abs_patch.py'}:/workspace/isaaclab_arena/embodiments/franka/franka.py",
                # Mount bootstrap
                "-v", f"{DEPS_DIR / 'run_eval.py'}:/workspace/data/run_eval.py",
                "-v", f"{DEPS_DIR / 'lightwheel_patch.py'}:/workspace/data/lightwheel_patch.py",
                # Mount heuristic policy (can be referenced by full module path)
                "-v", f"{DEPS_DIR / 'heuristic_policy.py'}:/workspace/data/heuristic_policy.py",
                # Mount small learned route classifier so the heuristic policy can
                # load it locally inside the container (rosclaw_darwin is not installed).
                "-v", f"{DEPS_DIR / 'route_classifier.py'}:/workspace/data/route_classifier.py",
                # Mount object validity audit policy
                "-v", f"{DEPS_DIR / 'object_validity_audit_policy.py'}:/workspace/data/object_validity_audit_policy.py",
                # Mount patched lift environment (uses procedural_table instead of table)
                "-v", f"{DEPS_DIR / 'lift_object_environment.py'}:/workspace/isaaclab_arena_environments/lift_object_environment.py",
                # Mount patched replay policy (fixes None-check ordering bug)
                "-v", "/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena/isaaclab_arena/policy/replay_action_policy.py:/workspace/isaaclab_arena/policy/replay_action_policy.py",
                # Mount TorchScript policy wrapper
                "-v", "/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena/isaaclab_arena/policy/torchscript_action_policy.py:/workspace/isaaclab_arena/policy/torchscript_action_policy.py",
                # Mount ONNX policy wrapper
                "-v", "/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena/isaaclab_arena/policy/onnx_action_policy.py:/workspace/isaaclab_arena/policy/onnx_action_policy.py",
                # Mount HDF5 recording directory (persist dataset recordings across container restarts)
                "-v", "/tmp/rosclaw_data/hdf5:/tmp/isaaclab/logs",
                # Mount episode trace directory so per-step traces survive container exit.
                "-v", f"{trace_mount_src}:/workspace/data/traces",
                # Mount test_data with official pretrained models (lift_object_model.pt)
                "-v", "/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena/isaaclab_arena/tests/test_data:/workspace/isaaclab_arena/tests/test_data",
                # Mount training logs/checkpoints so RSL-RL policies can load trained models
                "-v", "/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena/logs:/workspace/isaaclab_arena/logs",
                "-w", "/workspace",
                self.docker_image,
                "/isaac-sim/python.sh", "/workspace/data/run_eval.py",
                "--eval_jobs_config", "/workspace/data/eval_jobs.json",
            ])

            logger.info(f"Running Arena (docker): {' '.join(cmd[:12])} ...")

            # Save full stderr for debugging heuristic policies
            _stderr_path = tmp_path / "arena_stderr.log"

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=job.get("timeout_seconds", 1200),
                )
                _stderr_text = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr.decode("utf-8", errors="replace") if proc.stderr else "")
                _stderr_path.write_text(_stderr_text)
            except subprocess.TimeoutExpired as exc:
                _stderr_text = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
                _stderr_path.write_text(_stderr_text)
                return self._make_error_result(
                    run_id, task_id, policy_id, cmd, exc.stdout or "", _stderr_text, -1, started_at
                )
            except FileNotFoundError as exc:
                return self._make_error_result(
                    run_id, task_id, policy_id, cmd, "", str(exc), -1, started_at
                )

            finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            metrics_output = self._parse_metrics_output(proc.stdout)

            # Fallback: read metrics from shared file if stdout parsing failed
            # (IsaacSim may call os._exit() which skips Python finally blocks).
            if not metrics_output and metrics_path.exists():
                try:
                    file_data = json.loads(metrics_path.read_text())
                    if isinstance(file_data, dict):
                        metrics_output = file_data
                except (json.JSONDecodeError, ValueError):
                    pass

            metrics = self._extract_scalar_metrics(metrics_output)
            arena_metadata = dict(metrics_output) if metrics_output else {}

            # Determine status
            status = "failed"
            if proc.returncode == 0:
                # Even if docker exits 0, check for Isaac Sim / Arena errors in output
                if "Job" in proc.stdout and "failed with error" in proc.stdout:
                    status = "failed"
                elif "Job" in proc.stdout and "completed" in proc.stdout:
                    status = "completed"
                else:
                    status = "completed"

            # Treat container-side infrastructure errors (HDF5 locking, Python
            # tracebacks, PhysX stage failures, etc.) as runner failures even if
            # the Docker process exited 0.  These are not policy outcomes.
            stderr_full = proc.stderr or ""
            if _stderr_path.exists():
                try:
                    stderr_full = _stderr_path.read_text()
                except Exception:
                    pass
            infra_failure, infra_signals = self._detect_infrastructure_failure(stderr_full)
            if infra_failure:
                status = "failed"

            # TemporaryDirectory will delete tmpdir on exit; copy stderr to a
            # persistent location if the caller supplied an output directory.
            _persist_stderr = None
            if job.get("_out_dir"):
                _persist_stderr = Path(job["_out_dir"]) / f"{run_id}_stderr.log"
                try:
                    _persist_stderr.write_text(stderr_full)
                except Exception:
                    _persist_stderr = None

            result_metadata: dict[str, Any] = {
                "mode": "docker",
                "return_code": proc.returncode,
                "stdout_preview": proc.stdout[:2000],
                "stderr_preview": proc.stderr[:2000],
                "stderr_full": stderr_full[:50000],
                "arena_metrics_output": arena_metadata,
                "infrastructure_failure": infra_failure,
                "infrastructure_signals": infra_signals,
            }
            # Attach progress / episode metadata if provided by the container.
            for key in ("episode_metrics", "failure_counts", "policy_metadata"):
                if key in arena_metadata:
                    result_metadata[key] = arena_metadata[key]

            return EvaluationResult(
                run_id=run_id,
                task_id=task_id,
                policy_id=policy_id,
                adapter="arena",
                status=status,
                metrics=metrics,
                command=cmd,
                stdout_path=None,
                stderr_path=str(_persist_stderr) if _persist_stderr else None,
                started_at=started_at,
                finished_at=finished_at,
                metadata=result_metadata,
            )

    def _build_command(self, job: dict[str, Any]) -> list[str]:
        cmd = [self.python_bin, "-m", "isaaclab_arena.evaluation.eval_runner"]
        if job.get("policy_type"):
            cmd.extend(["--policy_type", str(job["policy_type"])])
        if job.get("num_steps"):
            cmd.extend(["--num_steps", str(job["num_steps"])])
        if job.get("num_episodes"):
            cmd.extend(["--num_episodes", str(job["num_episodes"])])
        if job.get("num_envs"):
            cmd.extend(["--num_envs", str(job["num_envs"])])
        if job.get("headless", True):
            cmd.append("--headless")
        if job.get("distributed"):
            cmd.append("--distributed")
        if job.get("enable_cameras"):
            cmd.append("--enable_cameras")
        if job.get("external_environment_class_path"):
            cmd.extend(["--external_environment_class_path", str(job["external_environment_class_path"])])
        return cmd

    @staticmethod
    def _parse_stdout(stdout: str) -> dict[str, float]:
        metrics: dict[str, float] = {}
        # 1. Try to extract JSON wrapped in <<<ROSCLAW_ARENA_METRICS>>> markers
        marker = "<<<ROSCLAW_ARENA_METRICS>>>"
        if marker in stdout:
            parts = stdout.split(marker)
            if len(parts) >= 3:
                try:
                    data = json.loads(parts[1].strip())
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, (int, float, bool)):
                                metrics[k] = float(v)
                            elif isinstance(v, dict):
                                for sk, sv in v.items():
                                    if isinstance(sv, (int, float, bool)):
                                        metrics[f"{k}_{sk}"] = float(sv)
                        return metrics
                except json.JSONDecodeError:
                    pass

        # 2. Fallback: scan for any JSON lines
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, (int, float)):
                                metrics[k] = float(v)
                except json.JSONDecodeError:
                    continue
        return metrics

    @staticmethod
    def _parse_metrics_output(stdout: str) -> dict[str, Any]:
        """Return the full metrics dictionary emitted by the container.

        Unlike ``_parse_stdout`` this preserves nested structures such as
        ``episode_metrics`` and ``policy_metadata``.
        """
        marker = "<<<ROSCLAW_ARENA_METRICS>>>"
        if marker in stdout:
            parts = stdout.split(marker)
            if len(parts) >= 3:
                try:
                    data = json.loads(parts[1].strip())
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    pass

        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue
        return {}

    @staticmethod
    def _extract_scalar_metrics(output: dict[str, Any]) -> dict[str, float]:
        """Flatten a metrics output dict into scalar metrics for ``EvaluationResult``."""
        metrics: dict[str, float] = {}
        if not isinstance(output, dict):
            return metrics
        for k, v in output.items():
            if isinstance(v, (int, float, bool)):
                metrics[k] = float(v)
            elif isinstance(v, dict):
                for sk, sv in v.items():
                    if isinstance(sv, (int, float, bool)):
                        metrics[f"{k}_{sk}"] = float(sv)
        return metrics

    def _make_error_result(
        self,
        run_id: str,
        task_id: str,
        policy_id: str,
        command: list[str],
        stdout: str,
        stderr: str,
        return_code: int,
        started_at: str,
    ) -> EvaluationResult:
        return EvaluationResult(
            run_id=run_id,
            task_id=task_id,
            policy_id=policy_id,
            adapter="arena",
            status="error",
            metrics={},
            command=command,
            stdout_path=None,
            stderr_path=None,
            started_at=started_at,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            metadata={
                "return_code": return_code,
                "stdout_preview": stdout[:2000],
                "stderr_preview": stderr[:2000],
                "error": stderr or "Arena subprocess failed",
            },
        )
