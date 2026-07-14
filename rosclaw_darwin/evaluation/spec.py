"""Evaluation specification schema.

Defines a declarative configuration for running a Darwin evaluation against a
benchmark backend such as ``lerobot-eval``. The spec is intentionally decoupled
from the runtime that executes it and from any LeRobot Python imports so it can
be loaded in lightweight tooling and CI environments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

SUPPORTED_BACKENDS: set[str] = {"lerobot_eval"}
EVAL_SPEC_SCHEMA_VERSION: str = "rosclaw.darwin.eval_spec.v1"


class PolicySpec(BaseModel):
    """Policy checkpoint and execution configuration."""

    path: str
    revision: str = "main"
    device: str = "cuda"
    use_amp: bool = False
    allow_network: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)


class EnvironmentSpec(BaseModel):
    """Benchmark environment configuration."""

    type: str
    task: str | None = None
    task_ids: list[str] | None = None
    batch_size: int = 2
    max_parallel_tasks: int = 1
    use_async_envs: bool = False
    trust_remote_code: bool = False
    overrides: dict[str, Any] = Field(default_factory=dict)


class EvaluationConfig(BaseModel):
    """Rollout / evaluation execution parameters."""

    n_episodes: int
    start_seed: int = 42
    timeout_sec: int = 1800
    probe_timeout_sec: int = 600
    render_episodes: int = 2
    recording: bool = False


class OutputConfig(BaseModel):
    """Artifact output and retention policy."""

    root: str
    keep_raw: bool = True
    keep_videos: bool = True
    keep_worker_dir: bool = False


class ValidityGates(BaseModel):
    """Gates that assert the evaluation produced valid evidence."""

    require_eval_info: bool = True
    require_expected_episode_count: bool = True
    require_all_tasks_completed: bool = True
    allow_nan_primary_metric: bool = False


class PerformanceGates(BaseModel):
    """Gates that assert the policy met a performance threshold."""

    minimum_success_rate: float | None = None
    minimum_macro_task_success_rate: float | None = None


class EvaluationSpec(BaseModel):
    """Top-level evaluation specification.

    Mirrors the YAML schema ``rosclaw.darwin.eval_spec.v1`` and is used to plan,
    execute, and audit a single evaluation run.
    """

    schema_version: Literal["rosclaw.darwin.eval_spec.v1"] = EVAL_SPEC_SCHEMA_VERSION
    id: str
    backend: str
    runtime: str | dict[str, Any]

    policy: PolicySpec
    environment: EnvironmentSpec
    evaluation: EvaluationConfig
    output: OutputConfig
    validity_gates: ValidityGates = Field(default_factory=ValidityGates)
    performance_gates: PerformanceGates = Field(default_factory=PerformanceGates)

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, value: str) -> str:
        if value not in SUPPORTED_BACKENDS:
            raise ValueError(
                f"Unsupported backend '{value}'. Supported backends: {sorted(SUPPORTED_BACKENDS)}"
            )
        return value

    @classmethod
    def from_path(cls, path: str | Path) -> "EvaluationSpec":
        """Load an evaluation spec from a YAML file."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def to_yaml(self, path: str | Path) -> None:
        """Serialize the spec to a YAML file."""
        Path(path).write_text(
            yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
