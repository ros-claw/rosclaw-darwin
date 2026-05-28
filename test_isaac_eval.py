"""Test real Isaac Sim evaluation in Docker."""
import sys
sys.path.insert(0, '/workspace/rosclaw-darwin')

# Stub missing isaaclab_teleop module (removed in newer IsaacLab)
sys.path.insert(0, '/workspace/rosclaw-darwin/stubs')

import os
os.environ['ROSCLAW_ARENA_MODE'] = 'docker'

from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter

print("[1] Loading task...")
loader = TaskLoader()
task = loader.load('/workspace/rosclaw-darwin/configs/tasks/pick_place_milk.yaml')
print(f"  Task: {task.name}")

print("[2] Building Arena adapter (docker mode)...")
adapter = ArenaAdapter(task, headless=True)
print(f"  Mode: {adapter._mode}")

try:
    adapter.build()
    print("  Build: SUCCESS")

    print("[3] Resetting environment...")
    obs = adapter.reset()
    print(f"  Obs keys: {list(obs.keys())}")

    print("[4] Taking one step...")
    import torch
    device = getattr(adapter._env, 'device', None) or getattr(adapter._env.unwrapped, 'device', torch.device('cuda:0'))
    action = torch.zeros(adapter._env.action_space.shape, device=device)
    obs, reward, done, info = adapter.step(action)
    print(f"  Reward: {reward}, Done: {done}")

    print("[5] Closing...")
    print("\n=== Isaac Sim evaluation WORKS! ===")
    adapter.close()

except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
