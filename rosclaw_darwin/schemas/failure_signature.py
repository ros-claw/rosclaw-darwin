"""Failure signature schema for Darwin v1.0."""

from __future__ import annotations

from pydantic import BaseModel


class FailureSignal(BaseModel):
    """A single diagnostic signal inside a failure signature."""

    name: str
    value: float | str | bool | None = None
    threshold: float | None = None
    evidence_path: str | None = None
