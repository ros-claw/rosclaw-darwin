"""ROSClaw-TDL schema: Pydantic models for task definition."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class Primitive(BaseModel):
    """A single motor primitive (skill) in a task."""

    name: str = Field(..., description="Primitive name, e.g. Pick, Place, Open")
    params: dict[str, Any] = Field(default_factory=dict, description="Primitive-specific parameters")
    target: str | None = Field(default=None, description="Target object or location")


class Object(BaseModel):
    """An object participating in the task."""

    name: str
    object_type: str = Field(default="generic", description="Semantic type, e.g. graspable, container")
    properties: dict[str, Any] = Field(default_factory=dict, description="Physical properties")
    initial_pose: dict[str, float] | None = Field(default=None, description="Initial position/orientation")


class Constraint(BaseModel):
    """A constraint that must be satisfied during execution."""

    name: str
    constraint_type: Literal["safety", "efficiency", "physical"] = "safety"
    description: str = ""
    weight: float = 1.0


class EvalConfig(BaseModel):
    """Evaluation configuration for a task."""

    max_steps: int = Field(default=1000, description="Maximum simulation steps")
    timeout_seconds: float = Field(default=120.0)
    success_criteria: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(
        default_factory=lambda: ["success_rate", "completion_time", "path_efficiency"]
    )
    repetitions: int = Field(default=1, description="Number of evaluation runs")


class Task(BaseModel):
    """A complete ROSClaw task definition."""

    id: str = Field(..., description="Globally unique task identifier")
    name: str = Field(..., description="Human-readable task name")
    version: str = Field(default="1.0")
    description: str = ""
    source: str = Field(default="rosclaw-tdl", description="Origin: rosclaw-tdl, bddl, robocasa, libero, ...")
    scene: str = Field(default="default", description="Scene identifier or layout name")
    primitives: list[Primitive] = Field(default_factory=list)
    objects: list[Object] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    eval_config: EvalConfig = Field(default_factory=EvalConfig)
    tags: list[str] = Field(default_factory=list)
    parent_id: str | None = Field(default=None, description="Parent task ID for evolution lineage")
    difficulty: float = Field(default=1.0, ge=0.0, le=10.0)

    def to_yaml(self) -> str:
        import yaml

        return yaml.dump(self.model_dump(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> Task:
        import yaml

        data = yaml.safe_load(text)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls.model_validate(data)
