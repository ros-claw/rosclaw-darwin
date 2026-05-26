"""EvolutionRunner: the core loop that measures how fast an agent evolves.

    Task
      |
      v
  Loop 1 (first attempt)
      |
      v
  Memory Consolidation  <-- force practice → SeekDB
      |
      v
  Loop 2 (retry)
      |
      v
  Evolution Score = delta(Loop1, Loop2)

The runner integrates with rosclaw-practice (capture) and
rosclaw-memory (consolidation) so the evaluation IS the learning.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from rosclaw_darwin.tdl.schema import Task
from rosclaw_darwin.environment.base import BaseEnvironmentAdapter
from rosclaw_darwin.evaluation.base import DarwinEvaluator
from rosclaw_darwin.evaluation.metrics import EvaluationMetrics
from rosclaw_darwin.integration.practice import PracticeBridge
from rosclaw_darwin.integration.memory import MemoryBridge


class EvolutionRunner:
    """Run the two-loop evolution evaluation for a single agent + task."""

    def __init__(
        self,
        adapter_factory: Callable[[Task], BaseEnvironmentAdapter],
        practice: PracticeBridge | None = None,
        memory: MemoryBridge | None = None,
        consolidation_delay: float = 2.0,
    ):
        self.adapter_factory = adapter_factory
        self.practice = practice or PracticeBridge()
        self.memory = memory or MemoryBridge()
        self.consolidation_delay = consolidation_delay
        self.results: list[dict[str, Any]] = []

    async def evaluate_evolution(
        self,
        task: Task,
        policy: Callable[[dict[str, Any]], dict[str, Any]],
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        """Run the full two-loop evolution evaluation.

        Returns a dict with:
            loop1: EvaluationMetrics
            loop2: EvaluationMetrics
            evolution_score: float   # 0.0 - 1.0
            sdr: float               # Skill Discovery Rate
            mie: float               # Memory Integration Efficiency
            session_id: str
        """
        session_id = f"evo_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        # --- Loop 1: first encounter (baseline) ---
        adapter1 = self.adapter_factory(task)
        evaluator1 = DarwinEvaluator(
            adapter1,
            practice_hook=self._make_practice_hook(session_id, "loop1"),
            memory_hook=self._make_memory_hook(task.id),
        )
        result1 = await evaluator1.evaluate(policy, max_steps=max_steps)

        # Force memory consolidation: wait for practice to flush to SeekDB.
        await asyncio.sleep(self.consolidation_delay)

        # Record the first attempt in SeekDB.
        self.memory.record_experience(
            task_id=task.id,
            session_id=f"{session_id}_loop1",
            outcome="success" if result1.success else "failure",
            metrics=result1.to_dict(),
        )

        # --- Loop 2: retry after consolidation ---
        adapter2 = self.adapter_factory(task)
        evaluator2 = DarwinEvaluator(
            adapter2,
            practice_hook=self._make_practice_hook(session_id, "loop2"),
            memory_hook=self._make_memory_hook(task.id),
        )
        result2 = await evaluator2.evaluate(policy, max_steps=max_steps)

        self.memory.record_experience(
            task_id=task.id,
            session_id=f"{session_id}_loop2",
            outcome="success" if result2.success else "failure",
            metrics=result2.to_dict(),
        )

        # --- Compute evolution scores ---
        evolution_score = self._calculate_evolution_score(result1, result2)
        sdr = self._calculate_sdr(result1, result2)
        mie = self._calculate_mie(result1, result2)

        report = {
            "session_id": session_id,
            "task_id": task.id,
            "loop1": result1.to_dict(),
            "loop2": result2.to_dict(),
            "evolution_score": evolution_score,
            "sdr": sdr,
            "mie": mie,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.results.append(report)
        return report

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_evolution_score(r1: EvaluationMetrics, r2: EvaluationMetrics) -> float:
        """Score 0-1 based on improvement from loop1 to loop2."""
        score = 0.0
        if (not r1.success) and r2.success:
            score += 0.5  # Core: went from fail to success.
        if r2.step_count < r1.step_count and r1.step_count > 0:
            score += 0.25 * (1.0 - r2.step_count / r1.step_count)
        if r2.collision_count < r1.collision_count:
            score += 0.25
        return min(score, 1.0)

    @staticmethod
    def _calculate_sdr(r1: EvaluationMetrics, r2: EvaluationMetrics) -> float:
        """Skill Discovery Rate: did the agent discover a new skill?"""
        # Simplistic: if loop2 succeeds with fewer steps, we infer skill discovery.
        if r2.success and r1.step_count > 0:
            improvement = 1.0 - (r2.step_count / max(r1.step_count, 1))
            return max(improvement, 0.0)
        return 0.0

    @staticmethod
    def _calculate_mie(r1: EvaluationMetrics, r2: EvaluationMetrics) -> float:
        """Memory Integration Efficiency: did memory reduce repeated errors?"""
        # If loop2 has fewer collisions than loop1, memory was integrated.
        if r1.collision_count > 0:
            return max(1.0 - (r2.collision_count / r1.collision_count), 0.0)
        return 1.0 if r2.collision_count == 0 else 0.0

    # ------------------------------------------------------------------
    # Hook factories
    # ------------------------------------------------------------------

    def _make_practice_hook(self, session_id: str, loop_label: str) -> Callable:
        def hook(**kwargs: Any) -> None:
            self.practice.submit(
                session_id=f"{session_id}_{loop_label}",
                task_id=kwargs.get("task_id", "unknown"),
                metrics=kwargs.get("metrics", {}),
                semantic_intent=f"Darwin evolution {loop_label}",
            )
        return hook

    def _make_memory_hook(self, task_id: str) -> Callable:
        def hook(**kwargs: Any) -> list[dict[str, Any]]:
            return self.memory.query(
                query_text=kwargs.get("query", task_id),
                n_results=5,
            )
        return hook
