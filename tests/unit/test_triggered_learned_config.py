"""Validate the triggered learned residual candidate policy config."""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parents[2] / "configs" / "policies" / "heuristic_servo_goal_pose_v3_triggered_learned.yaml"


def test_triggered_learned_config_exists_and_loads():
    assert CONFIG_PATH.exists(), CONFIG_PATH
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    assert cfg["policy_id"] == "heuristic_servo_goal_pose_v3_triggered_learned"
    assert cfg["type"] == "heuristic_servo_goal_pose"


def test_triggered_learned_residual_block():
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    pcfg = cfg["policy_config_dict"]
    assert pcfg["enable_residual_policy"] is True
    assert pcfg["residual_policy"] == "triggered_bounded_learned"
    assert "GRASP" in pcfg["residual_enabled_phases"]
    assert "LIFT" in pcfg["residual_enabled_phases"]
    assert pcfg["trigger_threshold"] == 0.5
    assert Path(pcfg["residual_policy_path"]).exists()
    assert Path(pcfg["trigger_model_path"]).exists()
