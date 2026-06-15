"""Integration test: FailureSignature export is written to run artifacts."""

from __future__ import annotations

import json

from rosclaw_darwin.evaluation.failure_signature import infer_failure_signatures_for_run
from rosclaw_darwin.evaluation.reproducibility import persist_run_artifacts
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.tdl.schema import EmbodimentSpec, EvalSpec, Primitive, SceneSpec, Task


def _make_task() -> Task:
    return Task(
        id="lift_object",
        name="lift_object",
        scene=SceneSpec(name="table"),
        embodiment=EmbodimentSpec(robot="franka"),
        objects=[],
        primitives=[Primitive(name="Lift")],
        eval=EvalSpec(max_steps=200),
    )


def test_failure_signatures_jsonl_export(tmp_path):
    task = _make_task()
    result = EvaluationResult(
        run_id="fsig_run_001",
        task_id=task.id,
        policy_id="heuristic_servo_lift",
        adapter="arena",
        status="completed",
        metrics={"success_rate": 0.5},
        failure_types={"target_not_reached_after_lift": 1},
    )
    episodes = [
        {"episode_id": 0, "success": True, "progress": 1.0, "failure_type": "none"},
        {"episode_id": 1, "success": False, "progress": 0.95, "failure_type": "target_not_reached_after_lift"},
    ]
    signatures = infer_failure_signatures_for_run(task, episodes)
    artifacts = persist_run_artifacts(
        run_dir=tmp_path / "run",
        result=result,
        task_yaml="task: lift_object\n",
        policy_config={"policy_id": "heuristic_servo_lift"},
        failure_signatures=[s.model_dump(mode="json") for s in signatures],
    )

    fs_path = artifacts["failure_signatures.jsonl"]
    assert fs_path.exists()
    lines = fs_path.read_text().strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["failure_type"] == "none"
    assert "high_progress_zero_success" in records[1]["signature_tags"]
