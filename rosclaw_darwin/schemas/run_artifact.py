"""Run artifact schema for Darwin v1.0."""

from __future__ import annotations

from rosclaw_darwin.evaluation.result import EvaluationResult


class RunArtifact(EvaluationResult):
    """A Darwin run artifact extends EvaluationResult with no extra fields.

    This thin subclass exists so the product schema surface has an explicit
    ``RunArtifact`` type, even though the canonical model remains
    ``EvaluationResult``.
    """
