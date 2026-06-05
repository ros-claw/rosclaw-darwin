"""Policy bridge: convert Darwin policy configs to Arena policy formats."""

from __future__ import annotations

from typing import Any


class PolicyBridge:
    """Translate policy configurations between Darwin and Arena."""

    @staticmethod
    def to_arena_policy(policy_config: dict[str, Any]) -> dict[str, Any]:
        return {
            "policy_type": policy_config.get("type", "zero"),
            "strength": policy_config.get("strength", 0.5),
            "checkpoint": policy_config.get("checkpoint"),
        }

    @staticmethod
    def from_arena_policy(arena_policy: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": arena_policy.get("policy_type", "zero"),
            "strength": arena_policy.get("strength", 0.5),
            "checkpoint": arena_policy.get("checkpoint"),
        }
