"""Tests for evolution engine."""

import pytest
from rosclaw_darwin.tdl.schema import Task, Primitive
from rosclaw_darwin.evolution.genome import TaskGenomeEngine
from rosclaw_darwin.evolution.runner import EvolutionRunner
from rosclaw_darwin.evaluation.metrics import EvaluationMetrics


class TestTaskGenomeEngine:
    def test_mutate_increases_difficulty(self):
        engine = TaskGenomeEngine()
        task = Task(id="base", name="Base", primitives=[Primitive(name="Pick")], difficulty=1.0)
        variants = engine.mutate(task, n_variations=3)
        assert len(variants) == 3
        for v in variants:
            assert v.parent_id == "base"
            assert v.difficulty >= task.difficulty

    def test_compose_chains_tasks(self):
        engine = TaskGenomeEngine()
        t1 = Task(id="t1", name="A", primitives=[Primitive(name="Pick")])
        t2 = Task(id="t2", name="B", primitives=[Primitive(name="Place")])
        composed = engine.compose([t1, t2])
        assert len(composed.primitives) == 2
        assert "composed_" in composed.id

    def test_generate_random(self):
        engine = TaskGenomeEngine()
        tasks = engine.generate_random(n_tasks=2, max_primitives=3)
        assert len(tasks) == 2
        for t in tasks:
            assert len(t.primitives) <= 3
            assert len(t.primitives) >= 1


class TestEvolutionRunner:
    def test_calculate_evolution_score(self):
        r1 = EvaluationMetrics(success=False, step_count=100, collision_count=5)
        r2 = EvaluationMetrics(success=True, step_count=80, collision_count=2)
        score = EvolutionRunner._calculate_evolution_score(r1, r2)
        assert score > 0.5  # success flip + fewer steps + fewer collisions

    def test_calculate_mie(self):
        r1 = EvaluationMetrics(success=False, collision_count=5)
        r2 = EvaluationMetrics(success=True, collision_count=1)
        mie = EvolutionRunner._calculate_mie(r1, r2)
        assert mie == 0.8  # 1 - 1/5

    def test_no_evolution_when_worse(self):
        r1 = EvaluationMetrics(success=True, step_count=50, collision_count=0)
        r2 = EvaluationMetrics(success=False, step_count=100, collision_count=5)
        score = EvolutionRunner._calculate_evolution_score(r1, r2)
        assert score == 0.0
