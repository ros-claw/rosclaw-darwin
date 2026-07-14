"""Base protocol and data models for Darwin evaluation backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from rosclaw_darwin.evaluation.result import EvaluationResult


@dataclass
class BackendProbe:
    """Result of probing a runtime/backend for a given evaluation spec.

    The probe is intentionally conservative: it reports ``ok`` only when the
    requested policy, environment and device are all statically verifiable.
    ``degraded`` means the runtime is present but some check could not be
    confirmed (e.g. a remote policy id or an optional import).  ``error``
    means a hard requirement is missing.
    """

    status: str  # ok | degraded | error
    messages: list[str] = field(default_factory=list)
    device: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationPlan:
    """Immutable execution plan produced before a backend run.

    The plan contains the exact command argv, resolved runtime, sanitized
    environment and all metadata needed to reproduce or audit a run.
    """

    run_id: str
    spec_hash: str
    backend: str
    runtime: dict[str, Any] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    benchmark: dict[str, Any] = field(default_factory=dict)
    expected_tasks: list[str] = field(default_factory=list)
    expected_episodes: int = 0
    output_dir: str = ""
    timeout_sec: int = 1800

    def ensure_output_dirs(self) -> tuple[Path, Path]:
        """Create the run output directory and the ``raw`` sub-directory."""
        root = Path(self.output_dir)
        raw_dir = root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        return root, raw_dir


@dataclass
class RawEvaluationRun:
    """Raw artifacts and metadata returned by ``EvaluationBackend.execute``.

    The raw run keeps the official benchmark output untouched.  Normalization
    into ``EvaluationResult`` happens separately via ``normalize``.
    """

    run_id: str
    output_dir: str
    returncode: int | None
    stdout_path: str
    stderr_path: str
    eval_info_path: str
    video_paths: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


class EvaluationBackend(Protocol):
    """Backend contract for running native benchmark evaluations.

    Implementations must not import heavy runtime dependencies (torch,
    lerobot, mujoco, etc.) at module load time.  Heavy imports are allowed
    only inside ``probe``/``execute`` or in worker subprocesses.
    """

    name: str

    def probe(self, spec: dict[str, Any]) -> BackendProbe:
        """Check whether the requested evaluation can be executed."""
        ...

    def plan(self, spec: dict[str, Any]) -> EvaluationPlan:
        """Build a deterministic execution plan from ``spec``."""
        ...

    def execute(self, plan: EvaluationPlan) -> RawEvaluationRun:
        """Run the planned command and capture raw evidence."""
        ...

    def normalize(
        self,
        raw_run: RawEvaluationRun,
        spec: dict[str, Any],
    ) -> EvaluationResult:
        """Normalize raw evidence into a Darwin ``EvaluationResult``."""
        ...
