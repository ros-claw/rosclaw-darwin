"""Policy metadata schema used to classify policies for reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class PolicyMetadata(BaseModel):
    """Metadata describing a policy's role in evaluation.

    Separates real policies from oracle/cheat policies and from replay/learned
    policies so that reports, leaderboards, and evolution scores can apply the
    right semantics.
    """

    policy_id: str = "unknown"
    policy_type: str = "unknown"
    policy_class: str = "normal"
    action_mode: str | None = None
    is_oracle: bool = False
    is_cheat: bool = False
    excluded_from_leaderboard: bool = False
    can_claim_capability: bool = True
    can_discover_skill: bool = True
    can_compute_evolution_score: bool = True
    description: str = ""

    @classmethod
    def from_policy_config(cls, config: dict[str, Any]) -> "PolicyMetadata":
        """Build metadata from a loaded policy config dict.

        Recognises both the explicit ``policy_metadata`` block and the flat
        legacy fields (``is_oracle``, ``is_cheat``, etc.) so older configs keep
        working.
        """
        cfg = dict(config or {})
        meta_block = cfg.get("policy_metadata") or {}
        if not isinstance(meta_block, dict):
            meta_block = {}

        def _get(*keys: str, default: Any = None) -> Any:
            for k in keys:
                if k in cfg:
                    return cfg[k]
                if k in meta_block:
                    return meta_block[k]
            return default

        is_oracle = bool(_get("is_oracle", default=False))
        is_cheat = bool(_get("is_cheat", default=False))
        excluded = bool(_get("excluded_from_leaderboard", default=False)) or is_oracle or is_cheat
        can_claim = bool(_get("can_claim_capability", default=not excluded))
        can_discover = bool(_get("can_discover_skill", default=not excluded))
        can_evolve = bool(_get("can_compute_evolution_score", default=not excluded))

        return cls(
            policy_id=cfg.get("policy_id", "unknown"),
            policy_type=cfg.get("type", cfg.get("policy_type", "unknown")),
            policy_class=_get("policy_class", default="normal"),
            action_mode=_get("action_mode"),
            is_oracle=is_oracle,
            is_cheat=is_cheat,
            excluded_from_leaderboard=excluded,
            can_claim_capability=can_claim,
            can_discover_skill=can_discover,
            can_compute_evolution_score=can_evolve,
            description=_get("description", default=""),
        )

    @classmethod
    def from_yaml_path(cls, path: str | Path) -> "PolicyMetadata":
        """Load policy metadata from a YAML config file."""
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cls.from_policy_config(cfg)

    def apply_exclusion(self, result: Any) -> None:
        """Mutate an ``EvaluationResult`` so oracle/cheat policies cannot claim
        capability, skill discovery, or evolution.

        This is intentionally decoupled from the result class so it can be
        called from adapters/runners after a result is constructed.
        """
        from rosclaw_darwin.evaluation.result import ClaimLevel, MetricScope

        if not (self.is_oracle or self.is_cheat or self.excluded_from_leaderboard):
            return

        result.metric_scope = MetricScope.pipeline_sanity
        result.claim_level = ClaimLevel.infrastructure
        result.can_claim_capability = False
        result.can_claim_evolution = False
        result.leaderboard_excluded = True
        result.exclusion_reason = self.description or "oracle/cheat policy excluded from capability claims"

        # Prevent evolution metrics from treating this as a skill.
        result.metrics.pop("skill_discovery_rate", None)
        result.metrics.pop("evolution_score", None)
        result.metrics.pop("skill_candidate_rate", None)
        result.metrics.pop("skill_validated_count", None)
        result.metrics.pop("skill_candidate_count", None)


def load_policy_metadata(config: dict[str, Any] | str | Path | None) -> PolicyMetadata:
    """Convenience loader accepting a dict, a YAML path, or None."""
    if config is None:
        return PolicyMetadata()
    if isinstance(config, (str, Path)):
        return PolicyMetadata.from_yaml_path(config)
    return PolicyMetadata.from_policy_config(config)
