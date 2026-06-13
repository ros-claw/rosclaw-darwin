"""Tests for failure-to-hint engine."""

from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine


class TestFailureToHint:
    def test_grasp_failed_generates_grasp_adjust(self):
        engine = FailureToHintEngine.from_yaml()
        hints = engine.suggest({"grasp_failed": 3})
        names = [h.name for h in hints]
        assert "grasp_adjust" in names
        assert any(h.source_failure_type == "grasp_failed" for h in hints)

    def test_no_failures_returns_empty(self):
        engine = FailureToHintEngine.from_yaml()
        assert engine.suggest({}) == []
        assert engine.suggest({"grasp_failed": 0}) == []

    def test_unknown_failure_returns_empty(self):
        engine = FailureToHintEngine.from_yaml()
        assert engine.suggest({"unknown_failure": 5}) == []

    def test_deduplication(self):
        engine = FailureToHintEngine.from_yaml()
        hints = engine.suggest({"grasp_failed": 1, "object_not_lifted": 1})
        names = [h.name for h in hints]
        # longer_gripper_close appears in both rules but should only appear once.
        assert names.count("longer_gripper_close") == 1

    def test_from_result(self):
        engine = FailureToHintEngine.from_yaml()
        result = EvaluationResult(
            run_id="r1",
            task_id="t1",
            policy_id="p1",
            adapter="mock",
            status="completed",
            failure_types={"timeout": 2},
        )
        hints = engine.suggest_from_result(result)
        assert any(h.name == "efficient_execution" for h in hints)
