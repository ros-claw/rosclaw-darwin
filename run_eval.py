"""Command-line evaluation runner for ROSClaw-Darwin.

Usage:
    python run_eval.py --task configs/tasks/pick_place_milk.yaml --policy zero
    python run_eval.py --task configs/tasks/pick_place_milk.yaml --policy random --repetitions 5
    python run_eval.py --task configs/tasks/open_fridge.yaml --policy heuristic --max-steps 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a policy on a ROSClaw-Darwin task.")
    parser.add_argument(
        "--task",
        required=True,
        help="Path to task YAML config (e.g., configs/tasks/pick_place_milk.yaml).",
    )
    policy_group = parser.add_mutually_exclusive_group()
    policy_group.add_argument(
        "--policy",
        choices=["zero", "random", "heuristic"],
        default="zero",
        help="Built-in policy to evaluate (default: zero).",
    )
    policy_group.add_argument(
        "--policy-module",
        dest="policy_module",
        default=None,
        help="Import path to external policy function: 'path/to/module.py:function_name'.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Override max steps per episode (default: task config).",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Number of independent episodes to run.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run simulation headless (default: True).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Show simulation GUI (overrides --headless).",
    )
    parser.add_argument(
        "--robot",
        default="franka",
        choices=["franka", "franka_ik", "franka_joint", "kuka_allegro"],
        help="Robot embodiment to use.",
    )
    parser.add_argument(
        "--device",
        default="cuda:0",
        help="Torch device for simulation.",
    )
    return parser


def _load_task(path: str):
    """Load a Task from YAML config."""
    from rosclaw_darwin.tdl.loader import TaskLoader

    loader = TaskLoader()
    return loader.load(path)


def _make_zero_policy(action_shape, device):
    """No-op policy."""
    import torch

    def policy(obs: dict[str, Any]):
        return torch.zeros(action_shape, device=device)

    return policy


def _make_random_policy(action_shape, device, scale: float = 0.2):
    """Random policy with bounded exploration."""
    import torch

    def policy(obs: dict[str, Any]):
        return torch.clamp(torch.randn(action_shape, device=device) * scale, -0.5, 0.5)

    return policy


def _load_external_policy(spec: str):
    """Load a policy function from 'path/to/module.py:function_name'.

    The policy function signature must be:
        fn(obs: dict[str, Any]) -> action (torch.Tensor | np.ndarray | dict)
    """
    import importlib.util
    import os

    if ":" not in spec:
        print(f"Error: --policy-module must be 'path:function_name', got: {spec}", file=sys.stderr)
        sys.exit(1)

    module_path, fn_name = spec.rsplit(":", 1)
    module_path = os.path.abspath(module_path)
    if not os.path.exists(module_path):
        print(f"Error: policy module not found: {module_path}", file=sys.stderr)
        sys.exit(1)

    spec_obj = importlib.util.spec_from_file_location("_external_policy", module_path)
    if spec_obj is None or spec_obj.loader is None:
        print(f"Error: cannot load module: {module_path}", file=sys.stderr)
        sys.exit(1)

    mod = importlib.util.module_from_spec(spec_obj)
    spec_obj.loader.exec_module(mod)
    if not hasattr(mod, fn_name):
        print(f"Error: function '{fn_name}' not found in {module_path}", file=sys.stderr)
        sys.exit(1)

    fn = getattr(mod, fn_name)
    if not callable(fn):
        print(f"Error: '{fn_name}' is not callable", file=sys.stderr)
        sys.exit(1)

    return fn


def _make_heuristic_policy(action_shape, device):
    """Simple heuristic: approach object from above, then grip and lift."""
    import torch

    def policy(obs: dict[str, Any]):
        action = torch.zeros(action_shape, device=device)
        eef_pos = obs.get("eef_pos")

        if eef_pos is not None:
            # Flatten to 1-D if batched
            pos = eef_pos[0] if hasattr(eef_pos, "dim") and eef_pos.dim() > 1 else eef_pos
            target_xy = torch.tensor([0.35, 0.0], device=device)
            dx = target_xy[0] - pos[0]
            dy = target_xy[1] - pos[1]
            dist_xy = torch.sqrt(dx**2 + dy**2)

            # Simple proportional control toward object
            action[0, 0] = torch.clamp(dx * 8.0, -2.0, 2.0)
            action[0, 1] = torch.clamp(dy * 8.0, -2.0, 2.0)
            action[0, 2] = 0.10  # descend
            action[0, 7] = -1.0 if dist_xy < 0.08 else 1.0  # close when close

        return action

    return policy


def main():
    parser = _build_parser()
    args = parser.parse_args()

    task_path = Path(args.task)
    if not task_path.exists():
        print(f"Error: task config not found: {task_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[DarwinEval] Loading task: {task_path}")
    task = _load_task(str(task_path))
    print(f"  Task ID:    {task.id}")
    print(f"  Name:       {task.name}")
    print(f"  Max steps:  {task.eval_config.max_steps}")
    print(f"  Robot:      {args.robot}")

    print("\n[DarwinEval] Building environment...")
    from rosclaw_darwin.environment.arena_adapter import ArenaAdapter

    headless = not args.gui if args.gui else args.headless
    adapter = ArenaAdapter(
        task,
        robot=args.robot,
        headless=headless,
        device=args.device,
    )
    adapter.build()
    print(f"  Backend: {adapter._mode}")
    print(f"  Built:   {adapter.is_built}")

    # Detect action shape and device from env
    env = adapter._env
    import torch

    action_shape = env.action_space.shape
    device = getattr(env, "device", None) or getattr(
        env.unwrapped, "device", torch.device(args.device)
    )
    print(f"  Action:  {action_shape}")
    print(f"  Device:  {device}")

    # Select policy
    if args.policy_module:
        policy = _load_external_policy(args.policy_module)
        print(f"\n[DarwinEval] Policy: external ({args.policy_module})")
    else:
        policy_map = {
            "zero": _make_zero_policy(action_shape, device),
            "random": _make_random_policy(action_shape, device),
            "heuristic": _make_heuristic_policy(action_shape, device),
        }
        policy = policy_map[args.policy]
        print(f"\n[DarwinEval] Policy: {args.policy}")
    print(f"[DarwinEval] Repetitions: {args.repetitions}")
    if args.max_steps:
        print(f"[DarwinEval] Max steps override: {args.max_steps}")

    # Run evaluation
    from rosclaw_darwin.evaluation.base import DarwinEvaluator

    evaluator = DarwinEvaluator(adapter)
    print(f"\n{'=' * 60}")

    results = evaluator.evaluate_repeated(policy, n=args.repetitions)

    print(f"{'=' * 60}")
    print("[DarwinEval] Results:")
    for i, m in enumerate(results):
        reward = m.info.get("total_reward", 0.0)
        print(f"  Episode {i + 1}: success={m.success}  steps={m.step_count}  reward={reward:.4f}  time={m.completion_time:.3f}s")

    agg = evaluator.aggregate()
    print(f"\n  Aggregated:")
    print(f"    Episodes:     {agg['episodes']}")
    print(f"    Success rate: {agg['success_rate']:.2%}")
    print(f"    Avg steps:    {agg['avg_step_count']:.1f}")
    print(f"    Avg time:     {agg['avg_completion_time']:.3f}s")

    adapter.close()
    print(f"\n[DarwinEval] Done.")


if __name__ == "__main__":
    main()
