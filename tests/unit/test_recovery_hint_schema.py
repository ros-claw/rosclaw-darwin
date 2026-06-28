"""Unit tests for FailureToHint v3.2 recovery-policy schema."""

from __future__ import annotations

from pathlib import Path

import yaml

from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine, SkillHint
from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry
from rosclaw_darwin.evolution.recovery_hint import (
    ActivationCondition,
    MonitorConfig,
    RecoveryPolicy,
    SuccessMetric,
)


def test_recovery_policy_defaults():
    policy = RecoveryPolicy(type="pause_stabilize")
    assert policy.type == "pause_stabilize"
    assert policy.max_attempts == 2
    assert policy.monitor.type == "slip_monitor"
    assert policy.activation_condition.phase_in == []
    assert policy.parameter_overrides == {}
    assert policy.success_metric == []
    assert policy.fallback_policy is None


def test_recovery_policy_nested_fields():
    policy = RecoveryPolicy(
        type="best_combined",
        max_attempts=2,
        monitor=MonitorConfig(
            type="slip_monitor", enabled=True, event_score_threshold=3.5, min_event_steps=5
        ),
        activation_condition=ActivationCondition(
            slip_score_gt=3.5,
            phase_in=["LIFT", "ALIGN"],
            consecutive_slip_steps=3,
            any_slip=True,
        ),
        parameter_overrides={"slip_recovery_pause_steps": 10},
        success_metric=[SuccessMetric(metric="orientation_achieved_rate")],
        fallback_policy=RecoveryPolicy(type="abort_safe", max_attempts=1),
    )
    assert policy.activation_condition.slip_score_gt == 3.5
    assert policy.success_metric[0].metric == "orientation_achieved_rate"
    assert policy.fallback_policy.type == "abort_safe"


def test_recipe_with_recovery_policy_merge():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="slip_recovery",
                source="auto_rule",
                trigger_tags=["torsional_slip"],
                hints=["enable_slip_monitor"],
                recovery_policy=RecoveryPolicy(
                    type="lower_regrip",
                    monitor=MonitorConfig(event_score_threshold=2.5),
                    activation_condition=ActivationCondition(consecutive_slip_steps=2),
                ),
            ),
            HintRecipe(
                name="plain_hint",
                source="auto_rule",
                trigger_tags=["torsional_slip"],
                hints=["stabilize_lift"],
            ),
        ]
    )
    selected, _overrides, _matched, _struct, _switches, recovery_policy = registry.select_hints(
        ["torsional_slip"]
    )
    assert "enable_slip_monitor" in selected
    assert recovery_policy is not None
    assert recovery_policy.type == "lower_regrip"
    assert recovery_policy.monitor.event_score_threshold == 2.5


def test_engine_attaches_recovery_policy_from_signatures(tmp_path: Path):
    rules = {
        "rules": [
            {
                "name": "torsional_slip_recovery",
                "failure_type": "torsional_slip",
                "hints": ["enable_slip_monitor"],
                "confidence": 0.7,
                "rationale": "slip",
            }
        ]
    }
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(yaml.safe_dump(rules))
    engine = FailureToHintEngine.from_yaml(rules_path)
    hints = engine.suggest({"torsional_slip": 1})
    assert len(hints) == 1
    assert hints[0].name == "enable_slip_monitor"
    # Coarse failure-type engine does not attach recovery policies.
    assert hints[0].recovery_policy is None


def test_skill_hint_recovery_policy_roundtrip():
    hint = SkillHint(
        name="enable_slip_monitor",
        source="auto_from_signature_v3",
        confidence=0.7,
        recovery_policy=RecoveryPolicy(type="place_push_correct", max_attempts=3),
    )
    data = hint.model_dump(mode="json")
    assert data["recovery_policy"]["type"] == "place_push_correct"
    restored = SkillHint(**data)
    assert restored.recovery_policy is not None
    assert restored.recovery_policy.max_attempts == 3


def test_v32_yaml_loads():
    path = Path(__file__).parent.parent.parent / "configs" / "skills" / "failure_signature_to_hint_rules_v32.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    assert any(r.recovery_policy is not None for r in registry.recipes)
    policy = next(r.recovery_policy for r in registry.recipes if r.recovery_policy is not None)
    assert policy.type in {"best_combined", "lower_regrip", "abort_residual_yaw"}
