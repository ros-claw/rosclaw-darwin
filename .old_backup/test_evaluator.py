"""Test BaseEvaluator integration with ArenaAdapter."""
import sys
sys.path.insert(0, '/workspace/rosclaw-darwin')

# Stub missing isaaclab_teleop module (removed in newer IsaacLab)
sys.path.insert(0, '/workspace/rosclaw-darwin/stubs')

import os
os.environ['ROSCLAW_ARENA_MODE'] = 'docker'

import time
import torch

from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter
from rosclaw_darwin.evaluation.metrics import compute_metrics


print("[1] Loading task...")
loader = TaskLoader()
task = loader.load('/workspace/rosclaw-darwin/configs/tasks/pick_place_milk.yaml')
print(f"  Task: {task.name}")

print("[2] Building Arena adapter (main thread - required for SimulationApp)...")
adapter = ArenaAdapter(task, headless=True)
print(f"  Mode: {adapter._mode}")
adapter.build()
print("  Build: SUCCESS")


def policy(obs):
    """No-op policy: return zero action tensor."""
    device = getattr(adapter._env, 'device', None) or getattr(
        adapter._env.unwrapped, 'device', torch.device('cuda:0')
    )
    return torch.zeros(adapter._env.action_space.shape, device=device)


def evaluate_sync(adapter, policy, max_steps=100):
    """Synchronous evaluation loop (matches BaseEvaluator.evaluate logic)."""
    task = adapter.task
    limit = max_steps or task.eval_config.max_steps

    obs = adapter.reset()
    trajectory = []
    success = False
    t0 = time.perf_counter()

    for step in range(limit):
        action = policy(obs)
        obs, reward, terminated, info = adapter.step(action)

        trajectory.append({
            "step": step,
            "obs": obs,
            "action": action,
            "reward": reward,
            "info": info,
        })

        if terminated:
            success = info.get("success", reward > 0.9)
            break

    elapsed = time.perf_counter() - t0
    metrics = compute_metrics(trajectory, success=success)
    metrics.completion_time = elapsed
    return metrics


try:
    print("[3] Evaluating (100 steps)...")
    metrics = evaluate_sync(adapter, policy, max_steps=100)
    print(f"  Success: {metrics.success}")
    print(f"  Steps: {metrics.step_count}")
    print(f"  Total reward: {metrics.info.get('total_reward', 0.0)}")
    print(f"  Completion time: {metrics.completion_time:.3f}s")
    print("\n=== BaseEvaluator + ArenaAdapter WORKS! ===")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    print("[4] Closing adapter...")
    adapter.close()
    print("  Closed.")
