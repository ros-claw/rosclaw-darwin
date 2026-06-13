"""Arena Docker smoke tests.

These tests require the rosclaw-darwin:arena-base Docker image and a GPU.
They are skipped by default; run with:

    pytest tests/arena -q --run-arena
"""

from __future__ import annotations

import os

import pytest

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, ObjectSpec, Primitive, SceneSpec, Task

pytestmark = pytest.mark.arena


def _should_run(request) -> bool:
    try:
        return request.config.getoption("--run-arena") is True
    except Exception:
        return os.environ.get("RUN_ARENA_TESTS", "0") == "1"


@pytest.fixture
def lift_task() -> Task:
    return Task(
        id="smoke_lift_object",
        name="Smoke Lift Object",
        scene=SceneSpec(name="table"),
        embodiment=EmbodimentSpec(robot="franka"),
        objects=[ObjectSpec(name="cube")],
        primitives=[Primitive(name="pick"), Primitive(name="lift")],
        eval=EvalSpec(max_steps=200, max_episodes=1),
    )


def test_arena_docker_smoke(lift_task: Task, request) -> None:
    if not _should_run(request):
        pytest.skip("Pass --run-arena or set RUN_ARENA_TESTS=1 to run Arena Docker tests")
    adapter = ArenaAdapter(lift_task, mode="docker")
    result = adapter.run_policy({"type": "zero_action", "policy_id": "zero_action"}, episodes=1)
    assert result.status == "completed"
    assert "success_rate" in result.metrics


def test_arena_skill_hint_consumption(lift_task: Task, request) -> None:
    if not _should_run(request):
        pytest.skip("Pass --run-arena or set RUN_ARENA_TESTS=1 to run Arena Docker tests")
    adapter = ArenaAdapter(lift_task, mode="docker")
    result = adapter.run_policy(
        {
            "type": "heuristic_lift",
            "policy_id": "heuristic_lift_with_hints",
            "policy_config_dict": {"skill_hints": ["grasp_adjust", "efficient_execution"]},
        },
        episodes=1,
    )
    assert result.status == "completed"
    # Hint consumption is logged to stderr inside the container; here we only verify the pipeline runs.
    assert result.stderr_path is not None or result.stdout_path is not None


def test_arena_servo_policy_smoke(lift_task: Task, request) -> None:
    if not _should_run(request):
        pytest.skip("Pass --run-arena or set RUN_ARENA_TESTS=1 to run Arena Docker tests")
    adapter = ArenaAdapter(lift_task, mode="docker")
    result = adapter.run_policy(
        {
            "type": "heuristic_servo_lift",
            "policy_id": "heuristic_servo_lift",
            "policy_config_dict": {
                "approach_offset_z": 0.08,
                "grasp_offset_z": 0.02,
                "lift_height": 0.25,
                "kp": 5.0,
            },
        },
        episodes=1,
    )
    assert result.status == "completed"
    assert "success_rate" in result.metrics
