"""Runtime registry for Darwin evaluation backends.

Provides a lightweight, file-backed registry of evaluation runtimes. A runtime
describes how to invoke a backend such as ``lerobot-eval``: either an external
Python environment on the host or a Docker image. No torch/lerobot imports are
allowed in this module so it can be imported in thin tooling and CI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

EVAL_RUNTIMES_SCHEMA_VERSION: str = "rosclaw.darwin.eval_runtimes.v1"
DEFAULT_DARWIN_HOME: str = "~/.rosclaw/darwin"


class EvalRuntime(BaseModel):
    """A registered evaluation runtime."""

    name: str
    mode: Literal["external", "docker"]
    python: str | None = None
    lerobot_eval: str | None = None
    image: str | None = None
    workdir: str | None = None
    gpu: bool = False
    environment: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


def get_darwin_home() -> Path:
    """Return the Darwin home directory.

    Uses ``ROSCLAW_DARWIN_HOME`` when set, otherwise falls back to
    ``~/.rosclaw/darwin``.
    """
    return Path(os.environ.get("ROSCLAW_DARWIN_HOME", DEFAULT_DARWIN_HOME)).expanduser().resolve()


def get_eval_runtimes_path() -> Path:
    """Return the path to the runtimes registry file."""
    return get_darwin_home() / "eval_runtimes.yaml"


def _migrate_runtimes(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy runtime dicts into the current schema."""
    if "runtimes" in data:
        return data["runtimes"]
    return data


def load_eval_runtimes() -> dict[str, EvalRuntime]:
    """Load the runtime registry from disk.

    Returns an empty dict if the registry file does not exist.
    """
    path = get_eval_runtimes_path()
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, dict):
        raw = _migrate_runtimes(raw)
    if not isinstance(raw, dict):
        raise ValueError(f"Runtime registry file {path} is not a mapping")
    return {
        name: EvalRuntime.model_validate({"name": name, **payload})
        for name, payload in raw.items()
        if isinstance(payload, dict)
    }


def save_eval_runtimes(runtimes: dict[str, EvalRuntime]) -> None:
    """Persist the runtime registry to disk."""
    path = get_eval_runtimes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": EVAL_RUNTIMES_SCHEMA_VERSION,
        "runtimes": {
            name: runtime.model_dump(mode="json", exclude={"name"})
            for name, runtime in runtimes.items()
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def register_runtime(name: str, runtime: EvalRuntime) -> EvalRuntime:
    """Register or update a runtime and persist the registry."""
    runtimes = load_eval_runtimes()
    runtime.name = name
    runtimes[name] = runtime
    save_eval_runtimes(runtimes)
    return runtime


def get_runtime(name: str) -> EvalRuntime:
    """Return a registered runtime by name.

    Raises ``KeyError`` if the runtime is not registered.
    """
    runtimes = load_eval_runtimes()
    if name not in runtimes:
        raise KeyError(f"No eval runtime registered with name '{name}'")
    return runtimes[name]


def list_runtimes() -> dict[str, EvalRuntime]:
    """Return a read-only snapshot of all registered runtimes."""
    return load_eval_runtimes()
