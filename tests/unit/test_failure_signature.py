"""Unit tests for FailureSignature v2 inference."""

from __future__ import annotations

import pytest

from rosclaw_darwin.evaluation.failure_signature import (
    FailureSignature,
    infer_failure_signature,
    infer_failure_signatures_for_run,
)
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, Primitive, SceneSpec, Task


def _make_task(task_id: str = "lift_object", primitives: list[str] | None = None) -> Task:
    return Task(
        id=task_id,
        name=task_id,
        scene=SceneSpec(name="table"),
        embodiment=EmbodimentSpec(robot="franka"),
        objects=[],
        primitives=[Primitive(name=p) for p in (primitives or ["Lift"])],
        eval=EvalSpec(max_steps=200),
    )


def test_high_progress_zero_success():
    task = _make_task()
    sig = infer_failure_signature(
        task=task,
        episode_metrics={
            "episode_id": 0,
            "success": False,
            "progress": 0.95,
            "failure_type": "target_not_reached_after_lift",
            "eef_to_object_distance_min": 0.01,
            "object_height_delta": 0.20,
            "object_to_target_distance_final": 0.04,
        },
        phase_trace=["APPROACH", "DESCEND", "GRASP", "LIFT"],
    )
    assert "high_progress_zero_success" in sig.signature_tags
    assert "lifted_but_not_aligned" in sig.signature_tags
    assert "final_alignment_gap" in sig.signature_tags
    assert sig.dominant_bottleneck == "final_alignment_gap"
    assert sig.object_lifted is True


def test_lifted_then_dropped():
    task = _make_task()
    sig = infer_failure_signature(
        task=task,
        episode_metrics={
            "episode_id": 1,
            "success": False,
            "progress": 0.7,
            "failure_type": "object_not_lifted",
            "eef_to_object_distance_min": 0.01,
            "object_height_initial": 0.05,
            "object_height_max": 0.25,
            "object_height_final": 0.06,
            "object_height_delta": 0.20,
        },
        phase_trace=["APPROACH", "DESCEND", "GRASP", "LIFT", "HOLD"],
    )
    assert "lifted_then_dropped" in sig.signature_tags
    assert "unstable_grasp" in sig.signature_tags
    assert sig.object_dropped is True


def test_not_reached():
    task = _make_task()
    sig = infer_failure_signature(
        task=task,
        episode_metrics={
            "episode_id": 2,
            "success": False,
            "progress": 0.1,
            "failure_type": "target_not_reached",
            "eef_to_object_distance_min": 0.15,
        },
    )
    assert "not_reached" in sig.signature_tags
    assert sig.reached_object is False


def test_orientation_gap():
    task = _make_task("goal_pose_001", ["orient"])
    sig = infer_failure_signature(
        task=task,
        episode_metrics={
            "episode_id": 3,
            "success": False,
            "progress": 0.6,
            "failure_type": "target_not_reached_after_lift",
            "eef_to_object_distance_min": 0.01,
            "object_height_delta": 0.15,
            "orientation_error_final": 0.25,
        },
    )
    assert sig.orientation_requirement_present is True
    assert "orientation_gap" in sig.signature_tags


def test_policy_noop():
    task = _make_task()
    sig = infer_failure_signature(
        task=task,
        episode_metrics={
            "episode_id": 4,
            "success": False,
            "progress": 0.0,
            "failure_type": "policy_noop",
        },
        trace=[{"action_norm": 0.0}, {"action_norm": 0.0}],
    )
    assert sig.mean_action_norm == pytest.approx(0.0)
    assert "policy_noop" in sig.signature_tags


def test_infer_failure_signatures_for_run():
    task = _make_task()
    episodes = [
        {"episode_id": 0, "success": True, "progress": 1.0, "failure_type": "none"},
        {"episode_id": 1, "success": False, "progress": 0.95, "failure_type": "target_not_reached_after_lift"},
    ]
    sigs = infer_failure_signatures_for_run(task, episodes)
    assert len(sigs) == 2
    assert sigs[0].failure_type == "none"
    assert "high_progress_zero_success" in sigs[1].signature_tags


def test_failure_signature_schema_defaults():
    sig = FailureSignature(task_id="t", episode_id=0, failure_type="timeout")
    assert sig.signature_tags == []
    assert sig.hint_relevant_tags == []
    assert sig.object_lifted is False
