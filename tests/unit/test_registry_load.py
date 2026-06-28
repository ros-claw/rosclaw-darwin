"""Unit tests for PromotionRegistry persistence and queries."""

from __future__ import annotations

import json

import pytest

from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.registry import PromotionRegistry


def test_registry_add_and_get(tmp_path):
    reg = PromotionRegistry(tmp_path)
    item = reg.add("seed24", kind="recovery", status="candidate_recovery", card="cards/seed24.card.yaml")
    assert item.id == "seed24"
    assert item.enabled_for_runtime is True

    loaded = reg.get("seed24")
    assert loaded is not None
    assert loaded.status == "candidate_recovery"


def test_registry_persists_to_json(tmp_path):
    reg = PromotionRegistry(tmp_path)
    reg.add("seed24", kind="recovery", status="candidate_recovery")

    new_reg = PromotionRegistry(tmp_path)
    item = new_reg.get("seed24")
    assert item is not None
    assert item.status == "candidate_recovery"

    data = json.loads((tmp_path / "registry.json").read_text())
    assert data["items"][0]["id"] == "seed24"
    assert "updated_at" in data


def test_registry_list_filtered(tmp_path):
    reg = PromotionRegistry(tmp_path)
    reg.add("seed24", kind="recovery", status="candidate_recovery")
    reg.add("large_yaw", kind="blocked", status="blocked_external")
    assert len(reg.list_items(kind="recovery")) == 1
    assert len(reg.list_items(status="blocked_external")) == 1


def test_registry_blocked_cannot_promote(tmp_path):
    reg = PromotionRegistry(tmp_path)
    reg.add("large_yaw", kind="blocked", status="blocked_external")
    with pytest.raises(ValueError):
        reg.add("large_yaw", kind="blocked", status="validated_recovery")


def test_registry_evaluate_paired_summary_promotes_to_candidate(tmp_path):
    summary = PairedEvaluationSummary(
        task_id="goal_pose_dex_cube_official",
        baseline_policy="baseline",
        candidate_policy="candidate",
        seed_range="0:199",
        valid_pairs=100,
        baseline_success_rate=0.99,
        candidate_success_rate=0.99,
        rescued_count=2,
        newly_failed_count=0,
        baseline_failed_seeds=[24, 198],
        candidate_failed_seeds=[],
        rescued_seeds=[24, 198],
        newly_failed_seeds=[],
    )
    reg = PromotionRegistry(tmp_path)
    item = reg.evaluate_paired_summary("seed24", summary, card="cards/seed24.card.yaml")
    assert item.status == "candidate_recovery"
    assert item.enabled_for_runtime is True


def test_registry_list_recoveries_by_task(tmp_path):
    reg = PromotionRegistry(tmp_path)
    reg.add("seed24", kind="recovery", status="candidate_recovery", card="seed24_goal_pose")
    reg.add("other", kind="recovery", status="candidate_recovery", card="other_task")
    recoveries = reg.list_recoveries(task_id="goal_pose")
    assert len(recoveries) == 1
    assert recoveries[0].id == "seed24"
