"""ROSClaw-Darwin end-to-end demonstration.

This script demonstrates the full Phase 1-3 pipeline:
  1. Load a task from YAML.
  2. Build an IsaacLab-Arena environment (mock mode if not installed).
  3. Run a simple random policy.
  4. Evaluate with DarwinEvaluator (integrates practice + memory).
  5. Run TaskGenomeEngine to generate task variations.
  6. Run EvolutionRunner for the two-loop evolution evaluation.
  7. Submit results to the EEIB Dashboard.
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

# Add repo root to path so we can import rosclaw_darwin before installation.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter
from rosclaw_darwin.evaluation.base import DarwinEvaluator
from rosclaw_darwin.evolution.genome import TaskGenomeEngine
from rosclaw_darwin.evolution.runner import EvolutionRunner
from rosclaw_darwin.integration.practice import PracticeBridge
from rosclaw_darwin.integration.memory import MemoryBridge


def random_policy(obs: dict) -> dict:
    """A trivial random policy for demonstration."""
    return {"action": random.choice(["pick", "place", "open", "close", "navigate"])}


async def main() -> None:
    print("=" * 60)
    print("ROSClaw-Darwin End-to-End Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Load task
    # ------------------------------------------------------------------
    print("\n[1] Loading tasks from YAML...")
    loader = TaskLoader(tasks_dir=str(ROOT / "configs" / "tasks"))
    task = loader.load(ROOT / "configs" / "tasks" / "pick_place_milk.yaml")
    print(f"    Loaded: {task.id} — {task.name}")
    print(f"    Primitives: {[p.name for p in task.primitives]}")
    print(f"    Objects: {[o.name for o in task.objects]}")

    # ------------------------------------------------------------------
    # 2. Build environment
    # ------------------------------------------------------------------
    print("\n[2] Building environment adapter...")
    adapter = ArenaAdapter(task, robot="franka", headless=True)
    adapter.build()
    state = adapter.get_state()
    print(f"    Backend: {state['backend']}")
    print(f"    Robot: {state['robot']}")

    # ------------------------------------------------------------------
    # 3. Run single evaluation
    # ------------------------------------------------------------------
    print("\n[3] Running single evaluation with random policy...")
    practice = PracticeBridge()
    memory = MemoryBridge()
    evaluator = DarwinEvaluator(adapter, practice_hook=practice.submit, memory_hook=memory.query)
    metrics = await evaluator.evaluate(random_policy)
    print(f"    Success: {metrics.success}")
    print(f"    Steps: {metrics.step_count}")
    print(f"    Collisions: {metrics.collision_count}")
    print(f"    Completion time: {metrics.completion_time:.3f}s")
    agg = evaluator.aggregate()
    print(f"    Aggregate: {agg}")

    # ------------------------------------------------------------------
    # 4. Task Genome: generate variations
    # ------------------------------------------------------------------
    print("\n[4] Generating task variations via Task Genome Engine...")
    genome = TaskGenomeEngine()
    variants = genome.mutate(task, n_variations=3)
    print(f"    Generated {len(variants)} variants:")
    for v in variants:
        print(f"      - {v.id}: {[p.name for p in v.primitives]} (difficulty={v.difficulty})")

    composed = genome.compose([task, variants[0]])
    print(f"    Composed task: {composed.id} with {len(composed.primitives)} primitives")

    # ------------------------------------------------------------------
    # 5. Evolution Runner: two-loop evaluation
    # ------------------------------------------------------------------
    print("\n[5] Running Evolution Runner (Loop 1 → Memory → Loop 2)...")

    def adapter_factory(t):
        a = ArenaAdapter(t, robot="franka", headless=True)
        a.build()
        return a

    runner = EvolutionRunner(
        adapter_factory=adapter_factory,
        practice=practice,
        memory=memory,
        consolidation_delay=0.5,
    )

    # Use a slightly smarter "policy" for loop2 that always succeeds
    # (simulating an agent that learned from loop1).
    loop_count = [0]

    def evolving_policy(obs: dict) -> dict:
        loop_count[0] += 1
        # Simulate learning: after enough steps, the agent "figures it out"
        if loop_count[0] > 100:
            return {"action": "success"}
        return random_policy(obs)

    report = await runner.evaluate_evolution(task, evolving_policy, max_steps=200)
    print(f"    Session: {report['session_id']}")
    print(f"    Loop1 success: {report['loop1']['success']}")
    print(f"    Loop2 success: {report['loop2']['success']}")
    print(f"    Evolution Score: {report['evolution_score']:.3f}")
    print(f"    SDR: {report['sdr']:.3f}")
    print(f"    MIE: {report['mie']:.3f}")

    # ------------------------------------------------------------------
    # 6. Dashboard submission
    # ------------------------------------------------------------------
    print("\n[6] Dashboard result preview...")
    dashboard_payload = {
        "agent_name": "demo_agent",
        "model": "random_policy_v1",
        "sdr": report["sdr"],
        "mie": report["mie"],
        "ssi": 0.0,
        "evolution_score": report["evolution_score"],
        "tasks_evaluated": 1,
        "timestamp": report["timestamp"],
    }
    print(f"    Dashboard payload: {dashboard_payload}")
    print(f"    (Run 'python -m rosclaw_darwin.dashboard.app' to start the web UI)")

    # Cleanup
    adapter.close()
    print("\n" + "=" * 60)
    print("Demo complete! All components functional.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
