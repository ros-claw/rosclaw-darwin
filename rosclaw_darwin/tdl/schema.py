"""ROSClaw-TDL schema: Pydantic models for task definition."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskHorizon(str, Enum):
    atomic = "atomic"
    short = "short"
    long = "long"
    composite = "composite"


class TaskSource(str, Enum):
    native = "native"
    arena = "arena"
    lw_benchhub = "lw_benchhub"
    robotwin = "robotwin"
    behavior1k = "behavior1k"
    robocasa = "robocasa"
    libero = "libero"
    unknown = "unknown"


class Affordance(str, Enum):
    graspable = "graspable"
    movable = "movable"
    openable = "openable"
    closeable = "closeable"
    pressable = "pressable"
    container = "container"
    surface = "surface"
    liquid = "liquid"
    deformable = "deformable"
    articulated = "articulated"
    navigable = "navigable"


class Primitive(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)


class ObjectSpec(BaseModel):
    name: str
    category: str | None = None
    affordances: list[Affordance | str] = Field(default_factory=list)
    native_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneSpec(BaseModel):
    name: str | None = None
    domain: str = "unknown"
    layout: str | None = None
    native_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbodimentSpec(BaseModel):
    robot: str
    control_mode: str | None = None
    enable_cameras: bool = False
    native_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalSpec(BaseModel):
    success_conditions: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    max_steps: int | None = None
    max_episodes: int | None = None


class MutationSpec(BaseModel):
    allowed: list[str] = Field(default_factory=list)
    difficulty: int = 1
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProvenanceSpec(BaseModel):
    source: TaskSource | str
    source_repo: str | None = None
    source_path: str | None = None
    source_commit: str | None = None
    native_env_name: str | None = None
    native_task_name: str | None = None
    native_config: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    id: str
    name: str
    description: str | None = None
    source: TaskSource | str = TaskSource.native
    domain: str = "unknown"
    horizon: TaskHorizon | str = TaskHorizon.atomic

    scene: SceneSpec
    embodiment: EmbodimentSpec
    objects: list[ObjectSpec] = Field(default_factory=list)
    primitives: list[Primitive] = Field(default_factory=list)

    constraints: list[str] = Field(default_factory=list)
    eval: EvalSpec = Field(default_factory=EvalSpec)
    mutation: MutationSpec = Field(default_factory=MutationSpec)
    provenance: ProvenanceSpec | None = None

    parents: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_yaml(self) -> str:
        import yaml
        return yaml.dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> Task:
        import yaml
        data = yaml.safe_load(text)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls.model_validate(data)
