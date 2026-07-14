"""Unit tests for the evaluation spec schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rosclaw_darwin.evaluation.spec import EvaluationSpec


def test_evaluation_spec_round_trip(tmp_path) -> None:
    """A spec can be serialized to YAML and restored unchanged."""
    spec = EvaluationSpec(
        id="pusht_diffusion_smoke",
        backend="lerobot_eval",
        runtime="lerobot_default",
        policy={
            "path": "lerobot/diffusion_pusht",
            "revision": "main",
            "device": "cuda",
            "use_amp": False,
            "allow_network": True,
            "overrides": {},
        },
        environment={
            "type": "pusht",
            "task": None,
            "task_ids": None,
            "batch_size": 2,
            "max_parallel_tasks": 1,
            "use_async_envs": False,
            "trust_remote_code": False,
            "overrides": {},
        },
        evaluation={
            "n_episodes": 2,
            "start_seed": 42,
            "timeout_sec": 1800,
            "render_episodes": 2,
            "recording": False,
        },
        output={
            "root": "data/eval_runs",
            "keep_raw": True,
            "keep_videos": True,
            "keep_worker_dir": False,
        },
        validity_gates={
            "require_eval_info": True,
            "require_expected_episode_count": True,
            "require_all_tasks_completed": True,
            "allow_nan_primary_metric": False,
        },
        performance_gates={
            "minimum_success_rate": None,
        },
    )
    path = tmp_path / "eval_spec.yaml"
    spec.to_yaml(path)
    restored = EvaluationSpec.from_path(path)

    assert restored.id == spec.id
    assert restored.backend == spec.backend
    assert restored.runtime == spec.runtime
    assert restored.policy.path == spec.policy.path
    assert restored.environment.type == spec.environment.type
    assert restored.evaluation.n_episodes == spec.evaluation.n_episodes
    assert restored.output.root == spec.output.root
    assert restored.validity_gates.require_eval_info == spec.validity_gates.require_eval_info
    assert restored.performance_gates.minimum_success_rate == spec.performance_gates.minimum_success_rate
    assert restored.schema_version == "rosclaw.darwin.eval_spec.v1"


def test_evaluation_spec_rejects_unknown_backend() -> None:
    """Validation fails when an unsupported backend is supplied."""
    with pytest.raises(ValidationError) as exc_info:
        EvaluationSpec(
            id="foo",
            backend="unknown_backend",
            runtime="default",
            policy={"path": "p"},
            environment={"type": "e"},
            evaluation={"n_episodes": 1},
            output={"root": "out"},
        )
    assert "unknown_backend" in str(exc_info.value)
    assert "Unsupported backend" in str(exc_info.value)
