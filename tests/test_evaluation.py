"""Tests for evaluation module."""

import pytest
from rosclaw_darwin.evaluation.metrics import compute_metrics, EvaluationMetrics
from rosclaw_darwin.tdl.schema import Task
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter
from rosclaw_darwin.evaluation.base import BaseEvaluator


class TestMetrics:
    def test_compute_success(self):
        trajectory = [
            {"reward": 0.0, "info": {"position": [0.0, 0.0]}},
            {"reward": 0.0, "info": {"position": [1.0, 0.0]}},
            {"reward": 1.0, "info": {"position": [2.0, 0.0]}},
        ]
        m = compute_metrics(trajectory, success=True)
        assert m.success is True
        assert m.step_count == 3
        assert m.path_length == 2.0

    def test_compute_with_collisions(self):
        trajectory = [
            {"reward": 0.0, "info": {"collision": True}},
            {"reward": 0.0, "info": {"collision": False}},
            {"reward": 0.0, "info": {"collision": True}},
        ]
        m = compute_metrics(trajectory, success=False)
        assert m.collision_count == 2


class TestBaseEvaluator:
    @pytest.mark.asyncio
    async def test_evaluate_mock(self):
        task = Task(id="mock_task", name="Mock")
        adapter = ArenaAdapter(task)
        adapter.build()
        evaluator = BaseEvaluator(adapter)

        def policy(obs):
            return {"action": "noop"}

        metrics = await evaluator.evaluate(policy, max_steps=5)
        assert metrics.step_count == 5  # mock reaches max_steps
        adapter.close()

    def test_aggregate(self):
        task = Task(id="agg", name="Aggregate")
        adapter = ArenaAdapter(task)
        evaluator = BaseEvaluator(adapter)
        evaluator.results = [
            EvaluationMetrics(success=True, completion_time=10.0, collision_count=1, step_count=50),
            EvaluationMetrics(success=False, completion_time=20.0, collision_count=3, step_count=100),
        ]
        agg = evaluator.aggregate()
        assert agg["episodes"] == 2
        assert agg["success_rate"] == 0.5
        assert agg["avg_completion_time"] == 15.0
