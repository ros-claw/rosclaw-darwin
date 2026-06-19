"""Tests for reachability risk estimation."""

from __future__ import annotations

from rosclaw_darwin.evaluation.reachability import (
    ReachabilityRiskEstimator,
)


def test_positive_y_positive_yaw_high_risk():
    estimator = ReachabilityRiskEstimator()
    risk = estimator.estimate((-0.5, 0.08, 0.2), object_yaw=0.2)
    assert risk.risk_level == "high"
    assert "positive_y_workspace_edge" in risk.risk_tags
    assert "positive_yaw_corner_collision" in risk.risk_tags
    assert risk.recommended_approach == "side_pregrasp_positive_y"


def test_positive_y_negative_yaw_low_risk():
    """Positive-y with negative yaw is not the failure cluster; keep direct_descend."""
    estimator = ReachabilityRiskEstimator()
    risk = estimator.estimate((-0.5, 0.08, 0.2), object_yaw=-0.2)
    assert risk.risk_level == "low"
    assert "positive_y_workspace_edge" not in risk.risk_tags
    assert "positive_yaw_corner_collision" not in risk.risk_tags
    assert risk.recommended_approach == "direct_descend"


def test_positive_y_no_yaw_high_risk():
    """Backward compatibility: yaw unknown keeps legacy positive-y high risk."""
    estimator = ReachabilityRiskEstimator()
    risk = estimator.estimate((-0.5, 0.08, 0.2))
    assert risk.risk_level == "high"


def test_low_risk():
    estimator = ReachabilityRiskEstimator()
    risk = estimator.estimate((-0.5, 0.0, 0.2))
    assert risk.risk_level == "low"
    assert risk.recommended_approach == "direct_descend"


def test_x_edge_medium_risk():
    estimator = ReachabilityRiskEstimator()
    risk = estimator.estimate((-0.75, 0.0, 0.2))
    assert risk.risk_level == "medium"
    assert "x_workspace_far_edge" in risk.risk_tags
    assert risk.recommended_approach == "high_pregrasp"


def test_custom_threshold():
    estimator = ReachabilityRiskEstimator(positive_y_threshold=0.10)
    risk = estimator.estimate((-0.5, 0.08, 0.2), object_yaw=0.2)
    assert risk.risk_level == "low"


def test_yaw_threshold_respected():
    estimator = ReachabilityRiskEstimator(
        positive_y_threshold=0.01, positive_yaw_threshold=0.10
    )
    # yaw below threshold -> not flagged (baseline direct_descend succeeds)
    risk = estimator.estimate((-0.5, 0.05, 0.2), object_yaw=0.05)
    assert risk.risk_level == "low"
    # yaw above threshold -> high
    risk = estimator.estimate((-0.5, 0.05, 0.2), object_yaw=0.15)
    assert risk.risk_level == "high"
