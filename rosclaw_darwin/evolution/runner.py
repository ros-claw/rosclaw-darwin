"""EvolutionRunner: the core loop that measures how fast an agent evolves."""

from __future__ import annotations

import copy
import time
import uuid
from typing import Any

from pydantic import BaseModel

from rosclaw_darwin.adapters.base import BaseEnvironmentAdapter
from rosclaw_darwin.evaluation.failure_signature import infer_failure_signatures_for_run
from rosclaw_darwin.evaluation.metrics import compute_evolution_metrics
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine
from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry
from rosclaw_darwin.evolution.skill_registry import SkillCandidate, SkillRegistry
from rosclaw_darwin.integration.how import HowBridge
from rosclaw_darwin.integration.memory import MemoryBridge
from rosclaw_darwin.integration.practice import PracticeBridge
from rosclaw_darwin.tdl.schema import Task


class EvolutionReport(BaseModel):
    run_id: str
    task_id: str
    policy_id: str
    loop_results: list[EvaluationResult]
    evolution_metrics: dict[str, float]
    discovered_skills: list[SkillCandidate] = []
    generated_tasks: list[str] = []
    artifacts: dict = {}




class EvolutionRunner:
    """Run the two-loop evolution evaluation for a single agent + task."""

    def __init__(
        self,
        adapter: BaseEnvironmentAdapter,
        practice_bridge=None,
        memory_bridge=None,
        how_bridge=None,
        config=None,
    ):
        self.adapter = adapter
        self.practice = practice_bridge or PracticeBridge()
        self.memory = memory_bridge or MemoryBridge()
        self.how = how_bridge or HowBridge()
        self.config = config or {}
        skill_config = dict(self.config.get("skill_discovery") or {})
        if "path" not in skill_config:
            skill_config["path"] = "data/skills/registry.json"
        self.skill_registry = SkillRegistry(skill_config)

    @staticmethod
    def _compute_skill_transfer_gain(
        loop1_metrics: dict[str, Any],
        loop2_metrics: dict[str, Any],
        had_auto_hints: bool,
    ) -> float:
        """Compute metric improvement attributable to auto-generated skill hints.

        Priority: success_rate > progress > object_height_delta > failure reduction.
        Returns 0.0 if no auto hints were applied.
        """
        if not had_auto_hints:
            return 0.0
        if "success_rate" in loop1_metrics and "success_rate" in loop2_metrics:
            return float(loop2_metrics["success_rate"]) - float(loop1_metrics["success_rate"])
        if "progress" in loop1_metrics and "progress" in loop2_metrics:
            return float(loop2_metrics["progress"]) - float(loop1_metrics["progress"])
        if "object_height_delta" in loop1_metrics and "object_height_delta" in loop2_metrics:
            return float(loop2_metrics["object_height_delta"]) - float(loop1_metrics["object_height_delta"])
        failures1 = loop1_metrics.get("num_failures")
        failures2 = loop2_metrics.get("num_failures")
        if failures1 is not None and failures2 is not None and failures1 > 0:
            return (failures1 - failures2) / failures1
        return 0.0

    def evolve(
        self,
        task: Task,
        policy_config: dict,
        loops: int = 2,
        episodes: int | None = None,
        auto_skill_hints: bool = False,
        hint_rules_path: str | None = None,
    ) -> dict[str, Any]:
        """Run the full evolution loop.

        Returns EvolutionReport as dict.
        """
        run_id = f"evo_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        loop_results: list[EvaluationResult] = []
        skill_hints_log: dict[str, list[dict[str, Any]]] = {}

        # --- Skill transfer: inject relevant validated skills into the policy ---
        relevant_skills = self.skill_registry.query_for_task(task)
        manual_or_validated_hints: list[str] = []
        if relevant_skills:
            manual_or_validated_hints = [s.name for s in relevant_skills]
            policy_config.setdefault("skill_hints", manual_or_validated_hints)

        skill_hints_log["loop_1"] = [
            {"name": h, "source": "validated_skill", "confidence": 1.0}
            for h in policy_config.get("skill_hints", [])
        ]

        # --- Loop 1: First Encounter ---
        result1 = self.adapter.run_policy(policy_config, episodes=episodes)
        loop_results.append(result1)

        # Practice event
        self.practice.submit_event(result1, task)

        # Memory record
        self.memory.record_experience(task, result1, evolution_run_id=run_id)

        # How: skill extraction
        experiences = self.memory.query_experiences(task)
        candidates = self.how.extract_skills(experiences)
        for c in candidates:
            c.source_task_ids.append(task.id)
            self.skill_registry.add(c)

        # Mutate / generate follow-up tasks
        generated_tasks: list[str] = []
        if not result1.metrics.get("success_rate", 0.0) >= 0.8:
            from rosclaw_darwin.evolution.mutators import MUTATOR_REGISTRY
            mutator_names = task.mutation.allowed or ["spatial", "object", "constraint"]
            for mname in mutator_names[:2]:
                mutator_cls = MUTATOR_REGISTRY.get(mname)
                if mutator_cls:
                    mutated = mutator_cls().mutate(task, seed=task.mutation.seed)
                    generated_tasks.append(mutated.id)

        # Consolidation: add memory bonus for loop 2
        consolidated = self.memory.consolidate(task)
        memory_bonus = consolidated.get("memory_bonus", 0.0)

        # --- Loop 2: Retry after learning ---
        policy2 = copy.deepcopy(policy_config)
        policy2["memory_bonus"] = memory_bonus

        auto_hints: list[dict[str, Any]] = []
        parameter_overrides: dict[str, Any] = {}
        structural_overrides: dict[str, Any] = {}
        strategy_switches: list[str] = []
        matched_recipes: list[str] = []
        if auto_skill_hints:
            engine = FailureToHintEngine.from_yaml(hint_rules_path)
            recipe_registry = HintRecipeRegistry.from_yaml()

            # Prefer rich FailureSignature v3 tags when traces are available.
            signatures: list[Any] = []
            if result1.artifacts.get("episode_metrics"):
                signatures = infer_failure_signatures_for_run(
                    task=task,
                    episode_metrics=result1.artifacts.get("episode_metrics", []),
                    phase_traces=result1.artifacts.get("phase_traces"),
                    traces=result1.artifacts.get("traces"),
                )
                signature_hints = engine.suggest_from_signatures(
                    signatures,
                    recipe_registry=recipe_registry,
                    task_id=task.id,
                )
            else:
                signature_hints = []

            if signature_hints:
                auto_hints = engine.to_dict(signature_hints)
                # Merge parameter and structural overrides from matched recipes.
                for hint in signature_hints:
                    parameter_overrides.update(hint.parameter_overrides)
                    structural_overrides.update(hint.structural_overrides)
                    for switch in hint.strategy_switches:
                        if switch not in strategy_switches:
                            strategy_switches.append(switch)
                matched_recipes = list(
                    dict.fromkeys(h.source_recipe for h in signature_hints if h.source_recipe)
                )
            else:
                # Fallback to coarse failure-type rules.
                auto_hints = engine.to_dict(engine.suggest_from_result(result1))

            if auto_hints:
                existing_hints = set(policy2.get("skill_hints", []))
                new_hint_names = [h["name"] for h in auto_hints if h["name"] not in existing_hints]
                policy2["skill_hints"] = list(existing_hints) + new_hint_names
                if parameter_overrides or structural_overrides:
                    policy2.setdefault("policy_config_dict", {})
                    policy2["policy_config_dict"] = {
                        **policy2["policy_config_dict"],
                        **parameter_overrides,
                        **structural_overrides,
                    }
                if strategy_switches:
                    policy2.setdefault("policy_config_dict", {})
                    existing_switches = set(policy2["policy_config_dict"].get("strategy_switches", []))
                    existing_switches.update(strategy_switches)
                    policy2["policy_config_dict"]["strategy_switches"] = sorted(existing_switches)
                policy2["_hint_source"] = {
                    "auto": auto_hints,
                    "manual": [h for h in policy2.get("skill_hints", []) if h in manual_or_validated_hints],
                    "loop": 1,
                    "matched_recipes": matched_recipes,
                    "parameter_overrides": parameter_overrides,
                    "structural_overrides": structural_overrides,
                    "strategy_switches": strategy_switches,
                }

        skill_hints_log["loop_2"] = [
            {
                "name": h,
                "source": "auto_from_signature_v3"
                if any(h == ah["name"] and ah.get("source") == "auto_from_signature_v3" for ah in auto_hints)
                else "auto_from_failure"
                if any(h == ah["name"] for ah in auto_hints)
                else "manual",
                "confidence": next(
                    (ah.get("confidence", 1.0) for ah in auto_hints if ah["name"] == h),
                    1.0,
                ),
            }
            for h in policy2.get("skill_hints", [])
        ]

        result2 = self.adapter.run_policy(policy2, episodes=episodes)
        loop_results.append(result2)

        self.practice.submit_event(result2, task)
        self.memory.record_experience(task, result2, evolution_run_id=run_id)

        # Re-extract skills using both loops of the current evolution run
        experiences = self.memory.query_experiences(task, evolution_run_id=run_id)
        candidates = self.how.extract_skills(experiences)
        for c in candidates:
            c.source_task_ids.append(task.id)
            self.skill_registry.add(c)

        # Evolution metrics
        l1 = {
            **result1.metrics,
            "num_failures": (task.eval.max_episodes or 20) - int(result1.metrics.get("num_success", 0)),
        }
        l2 = {
            **result2.metrics,
            "num_failures": (task.eval.max_episodes or 20) - int(result2.metrics.get("num_success", 0)),
        }
        evo_metrics = compute_evolution_metrics(l1, l2)

        # Skill discovery metrics from registry
        validated_skills = self.skill_registry.list_skills()
        candidate_skills = self.skill_registry.list_candidates()
        evo_metrics["skill_discovery_rate"] = len(validated_skills) / max(1, len(loop_results))
        evo_metrics["skill_candidate_rate"] = len(candidate_skills) / max(1, len(loop_results))
        evo_metrics["skill_validated_count"] = float(len(validated_skills))
        evo_metrics["skill_candidate_count"] = float(len(candidate_skills))
        evo_metrics["skill_transfer_gain"] = self._compute_skill_transfer_gain(
            result1.metrics, result2.metrics, bool(auto_hints)
        )

        report = {
            "run_id": run_id,
            "task_id": task.id,
            "policy_id": policy_config.get("policy_id", "unknown"),
            "loop_results": [r.model_dump(mode="json") for r in loop_results],
            "evolution_metrics": evo_metrics,
            "discovered_skills": [s.model_dump(mode="json") for s in validated_skills],
            "candidate_skills": [s.model_dump(mode="json") for s in candidate_skills],
            "generated_tasks": generated_tasks,
            "skill_hints": skill_hints_log,
            "hint_source": policy2.get("_hint_source", {}),
            "artifacts": {},
        }
        return report
