#!/usr/bin/env python3
"""Quick test for Arena episode-based evaluation via Docker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rosclaw_darwin.tdl.schema import Task
from rosclaw_darwin.adapters.arena import ArenaAdapter

# Load a simple task
task_path = Path("examples/tasks/native/lift_object.yaml")
if not task_path.exists():
    print(f"Task not found: {task_path}")
    sys.exit(1)

task = Task.from_yaml(task_path.read_text())

# Force docker mode
import os
os.environ["ROSCLAW_ARENA_MODE"] = "docker"

adapter = ArenaAdapter(task, mode="docker")

# Test with num_episodes=1, zero_action policy
policy_config = {
    "policy_id": "zero_action",
    "policy_type": "zero_action",
    "policy_config_dict": {},
}

print("Running Arena Docker with num_episodes=1 ...")
result = adapter.run_policy(policy_config, episodes=1)

print(f"Status: {result.status}")
print(f"Metrics: {result.metrics}")
print(f"Return code: {result.metadata.get('return_code')}")
print("--- stdout preview ---")
print(result.metadata.get("stdout_preview", "")[-1000:])
print("--- stderr preview ---")
print(result.metadata.get("stderr_preview", "")[-500:])
