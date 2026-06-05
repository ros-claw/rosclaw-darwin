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

# Monkey-patch MetricsLogger to capture metrics so we can print them as JSON.
_captured_metrics: dict[str, dict] = {}
try:
    from isaaclab_arena.metrics.metrics_logger import MetricsLogger

    _orig_append = MetricsLogger.append_job_metrics

    def _patched_append(self, job_name, metrics):
        _orig_append(self, job_name, metrics)
        if metrics:
            _captured_metrics[job_name] = metrics

    MetricsLogger.append_job_metrics = _patched_append
except Exception:
    pass

# Monkey-patch JobManager to capture job completion status.
_captured_jobs: dict[str, dict] = {}
try:
    from isaaclab_arena.evaluation.job_manager import JobManager

    _orig_complete = JobManager.complete_job

    def _patched_complete(self, job, metrics=None, status=None):
        _orig_complete(self, job, metrics=metrics, status=status)
        _captured_jobs[job.name] = {
            "status": str(status) if status else None,
            "num_steps": job.num_steps,
            "num_episodes": job.num_episodes,
        }

    JobManager.complete_job = _patched_complete
except Exception:
    pass

from isaaclab_arena.evaluation.eval_runner import main

if __name__ == "__main__":
    try:
        main()
    finally:
        import json

        output: dict[str, object] = {}
        if _captured_metrics:
            for job_name, metrics in _captured_metrics.items():
                for k, v in metrics.items():
                    output[f"{job_name}_{k}"] = v
        if _captured_jobs:
            for job_name, info in _captured_jobs.items():
                if info.get("num_steps") is not None:
                    output[f"{job_name}_num_steps"] = info["num_steps"]
                if info.get("num_episodes") is not None:
                    output[f"{job_name}_num_episodes"] = info["num_episodes"]
                output[f"{job_name}_status"] = info.get("status", "unknown")
        if not output:
            output["note"] = "execution_completed"
        print(json.dumps(output))
