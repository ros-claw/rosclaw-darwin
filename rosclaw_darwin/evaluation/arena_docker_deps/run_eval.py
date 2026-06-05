import sys
# Inject --headless before AppLauncher initializes so it picks headless kit
if "--headless" not in sys.argv:
    sys.argv.insert(1, "--headless")

sys.path.insert(0, "/workspace/data")
import lightwheel_patch

# Monkey-patch wp.to_torch for OmniWarp 1.12.0 + PyTorch 2.7 compatibility.
try:
    import warp as wp
    import torch

    _orig_to_torch = wp.to_torch

    def _compat_to_torch(a, requires_grad=None):
        if isinstance(a, torch.Tensor):
            return a
        return _orig_to_torch(a, requires_grad)

    wp.to_torch = _compat_to_torch
except Exception:
    pass

# Shared state for metrics capture.
_captured_metrics: dict[str, dict] = {}
_captured_rollout: dict[str, dict] = {}
_captured_jobs: dict[str, dict] = {}


def _write_metrics_file() -> None:
    """Persist captured metrics to a shared file so the host can read them
    even if IsaacSim calls os._exit() and skips Python finally blocks."""
    import json

    output: dict[str, object] = {}

    # Source 1: captured from MetricsLogger.append_job_metrics
    if _captured_metrics:
        for job_name, metrics in _captured_metrics.items():
            for k, v in metrics.items():
                output[f"{job_name}_{k}"] = v

    # Source 2: captured from JobManager.complete_job
    if _captured_jobs:
        for job_name, info in _captured_jobs.items():
            if info.get("num_steps") is not None:
                output[f"{job_name}_num_steps"] = info["num_steps"]
            if info.get("num_episodes") is not None:
                output[f"{job_name}_num_episodes"] = info["num_episodes"]
            output[f"{job_name}_status"] = info.get("status", "unknown")
            if info.get("metrics"):
                for k, v in info["metrics"].items():
                    output[f"{job_name}_jobmetric_{k}"] = v

    # Source 3: captured from rollout_policy return value
    if _captured_rollout.get("last"):
        last = _captured_rollout["last"]
        if last.get("metrics"):
            for k, v in last["metrics"].items():
                output[f"rollout_{k}"] = v
        output["rollout_num_steps"] = last.get("num_steps")
        output["rollout_num_episodes"] = last.get("num_episodes")

    if not output:
        output["note"] = "execution_completed"

    try:
        with open("/workspace/data/metrics_output.json", "w") as f:
            json.dump(output, f)
    except Exception:
        pass

    # Also try stdout with strong delimiters.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        marker = "<<<ROSCLAW_ARENA_METRICS>>>"
        sys.stdout.write(f"\n{marker}\n")
        sys.stdout.write(json.dumps(output))
        sys.stdout.write(f"\n{marker}\n")
        sys.stdout.flush()
    except Exception:
        pass


# 1. Monkey-patch rollout_policy BEFORE eval_runner imports it.
try:
    from isaaclab_arena.evaluation import policy_runner as _pr_mod

    _orig_rollout = _pr_mod.rollout_policy

    def _patched_rollout(env, policy, num_steps=None, num_episodes=None, language_instruction=None):
        step_log: list[dict] = []
        _orig_step = env.step

        def _patched_step(action):
            obs, reward, terminated, truncated, info = _orig_step(action)
            step_log.append({
                "step": len(step_log),
                "terminated": terminated.any().item(),
                "truncated": truncated.any().item(),
                "reward": float(reward) if hasattr(reward, "item") else float(reward),
            })
            return obs, reward, terminated, truncated, info

        env.step = _patched_step
        metrics = _orig_rollout(env, policy, num_steps, num_episodes, language_instruction)
        env.step = _orig_step

        enriched_metrics = dict(metrics) if metrics else {}
        enriched_metrics["_step_count"] = len(step_log)
        enriched_metrics["_episode_lengths"] = [i["step"] + 1 for i in step_log if i["terminated"] or i["truncated"]]
        if step_log:
            enriched_metrics["_first_terminated"] = int(step_log[0]["terminated"])
            enriched_metrics["_first_truncated"] = int(step_log[0]["truncated"])
            enriched_metrics["_last_terminated"] = int(step_log[-1]["terminated"])
            enriched_metrics["_last_truncated"] = int(step_log[-1]["truncated"])
        _captured_rollout["last"] = {
            "metrics": enriched_metrics,
            "num_steps": num_steps,
            "num_episodes": num_episodes,
        }
        _write_metrics_file()
        return metrics

    _pr_mod.rollout_policy = _patched_rollout
except Exception:
    pass

# 2. Monkey-patch MetricsLogger.append_job_metrics.
try:
    from isaaclab_arena.metrics.metrics_logger import MetricsLogger

    _orig_append = MetricsLogger.append_job_metrics

    def _patched_append(self, job_name, metrics):
        _orig_append(self, job_name, metrics)
        if metrics:
            _captured_metrics[job_name] = metrics
        _write_metrics_file()

    MetricsLogger.append_job_metrics = _patched_append
except Exception:
    pass

# 3. Monkey-patch JobManager.complete_job.
try:
    from isaaclab_arena.evaluation.job_manager import JobManager

    _orig_complete = JobManager.complete_job

    def _patched_complete(self, job, metrics=None, status=None):
        _orig_complete(self, job, metrics=metrics, status=status)
        _captured_jobs[job.name] = {
            "status": str(status) if status else None,
            "num_steps": job.num_steps,
            "num_episodes": job.num_episodes,
            "metrics": metrics,
        }
        _write_metrics_file()

    JobManager.complete_job = _patched_complete
except Exception:
    pass

# Import eval_runner AFTER patching policy_runner so the imported
# rollout_policy reference points to our patched function.
from isaaclab_arena.evaluation.eval_runner import main

if __name__ == "__main__":
    try:
        main()
    finally:
        _write_metrics_file()
