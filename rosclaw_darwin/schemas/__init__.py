"""Consolidated Darwin v1.0 schema surface.

All models are re-exported from their canonical locations so that older imports
continue to work while new code can import from a single product namespace.
"""

from __future__ import annotations

# Evaluation layer
from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evaluation.object_validity import (
    ObjectValidityReport,
    check_object_validity,
)
from rosclaw_darwin.evaluation.paired_evaluation import (
    PairedEvaluationResult,
    PairedEvaluationSummary,
    PairedSeedOutcome,
    classify_pair,
    compute_paired_summary,
)
from rosclaw_darwin.evaluation.policy_metadata import PolicyMetadata
from rosclaw_darwin.evaluation.reachability import ReachabilityRisk
from rosclaw_darwin.evaluation.result import ClaimLevel, EvaluationResult, MetricScope

# Evolution / promotion layer
from rosclaw_darwin.evolution.evidence_status import EvidenceStatus
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintRule, SkillHint
from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry
from rosclaw_darwin.evolution.recovery_hint import (
    ActivationCondition,
    MonitorConfig,
    RecoveryHint,
    RecoveryPolicy,
    SuccessMetric,
)
from rosclaw_darwin.evolution.runner import EvolutionReport
from rosclaw_darwin.evolution.skill_registry import SkillCandidate, SkillRegistry

# Learning / residual layer
from rosclaw_darwin.learning.residual_policy import ResidualAction

# Local schema modules
from rosclaw_darwin.schemas.evidence_card import EvidenceCard
from rosclaw_darwin.schemas.failure_signature import FailureSignal
from rosclaw_darwin.schemas.intervention import CandidateIntervention
from rosclaw_darwin.schemas.promotion_decision import PromotionDecision
from rosclaw_darwin.schemas.run_artifact import RunArtifact
from rosclaw_darwin.schemas.task_validity import TaskValidity

# Task definition layer
from rosclaw_darwin.tdl.schema import (
    Affordance,
    EmbodimentSpec,
    EvalSpec,
    ExecutionBackend,
    ExecutionMode,
    ExecutionSpec,
    MutationSpec,
    ObjectSpec,
    Primitive,
    ProvenanceSpec,
    SceneSpec,
    Task,
    TaskHorizon,
    TaskSource,
)

__all__ = [
    # Task definition
    "Task",
    "Primitive",
    "ObjectSpec",
    "SceneSpec",
    "EmbodimentSpec",
    "EvalSpec",
    "ExecutionSpec",
    "MutationSpec",
    "ProvenanceSpec",
    "TaskHorizon",
    "TaskSource",
    "ExecutionBackend",
    "ExecutionMode",
    "Affordance",
    # Evaluation
    "EvaluationResult",
    "MetricScope",
    "ClaimLevel",
    "ObjectValidityReport",
    "check_object_validity",
    "FailureSignature",
    "PairedEvaluationResult",
    "PairedEvaluationSummary",
    "PairedSeedOutcome",
    "classify_pair",
    "compute_paired_summary",
    "PolicyMetadata",
    "ReachabilityRisk",
    # Evolution
    "EvidenceStatus",
    "HintRecipe",
    "HintRecipeRegistry",
    "SkillHint",
    "FailureToHintRule",
    "RecoveryPolicy",
    "MonitorConfig",
    "ActivationCondition",
    "SuccessMetric",
    "RecoveryHint",
    "EvolutionReport",
    "SkillCandidate",
    "SkillRegistry",
    # Learning
    "ResidualAction",
    # Local product schemas
    "TaskValidity",
    "FailureSignal",
    "CandidateIntervention",
    "PromotionDecision",
    "EvidenceCard",
    "RunArtifact",
]
