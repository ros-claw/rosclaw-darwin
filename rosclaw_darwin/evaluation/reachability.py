"""Reachability risk estimation for manipulation tasks.

This module provides a lightweight, kinematic-free reachability check based on
object position relative to the robot base.  It is intentionally conservative:
it flags seeds that are likely to hit the workspace boundary so that the policy
can choose an alternative approach path.
"""

from __future__ import annotations

from pydantic import BaseModel


class ReachabilityRisk(BaseModel):
    """Reachability risk assessment for a target object pose."""

    object_x: float
    object_y: float
    object_z: float
    risk_level: str  # low | medium | high
    risk_tags: list[str]
    recommended_approach: str
    rationale: str


class ReachabilityRiskEstimator:
    """Estimate reachability risk from object pose and optional workspace limits.

    The default thresholds are tuned for the Franka + table setup used in the
    ROSClaw-Darwin dex_cube experiments.  Positive-y object locations are the
    dominant failure mode because the default reset pose cannot reach them
    without a collision or kinematic limit.
    """

    def __init__(
        self,
        positive_y_threshold: float = 0.01,
        positive_yaw_threshold: float = 0.0,
        negative_y_threshold: float = -0.35,
        min_reachable_x: float = -0.70,
        max_reachable_x: float = -0.20,
        table_z: float = 0.18,
        table_margin: float = 0.02,
    ):
        self.positive_y_threshold = positive_y_threshold
        self.positive_yaw_threshold = positive_yaw_threshold
        self.negative_y_threshold = negative_y_threshold
        self.min_reachable_x = min_reachable_x
        self.max_reachable_x = max_reachable_x
        self.table_z = table_z
        self.table_margin = table_margin

    def estimate(
        self,
        object_pos: tuple[float, float, float],
        robot_base_pos: tuple[float, float, float] | None = None,
        object_yaw: float | None = None,
    ) -> ReachabilityRisk:
        """Return a reachability risk for the given object position and yaw."""
        x, y, z = object_pos
        risk_tags: list[str] = []

        # Only flag the positive-y workspace edge when the object also has a
        # positive (or unknown) yaw.  Data from the 100-seed benchmark shows that
        # positive-y placements with negative yaw succeed with the default
        # straight-line approach; treating them as medium risk and raising to a
        # high pregrasp actually causes regressions.
        yaw_positive = object_yaw is None or object_yaw > self.positive_yaw_threshold
        if y > self.positive_y_threshold and yaw_positive:
            risk_tags.append("positive_y_workspace_edge")
            risk_tags.append("positive_yaw_corner_collision")
            return ReachabilityRisk(
                object_x=x,
                object_y=y,
                object_z=z,
                risk_level="high",
                risk_tags=risk_tags,
                recommended_approach="side_pregrasp_positive_y",
                rationale=(
                    "Object is on the positive-y side of the table with a positive "
                    "yaw; the default reset pose cannot reach it directly without "
                    "corner collision. Use a side pregrasp from the negative-y side."
                ),
            )

        # Other workspace-edge tags (x/negative-y/low height) can still be reported
        # as medium risk, but the policy should treat medium risk conservatively
        # because the high-pregrasp intervention has not been shown to help on
        # dex_cube.
        if y < self.negative_y_threshold:
            risk_tags.append("negative_y_workspace_edge")
        if x < self.min_reachable_x:
            risk_tags.append("x_workspace_far_edge")
        if x > self.max_reachable_x:
            risk_tags.append("x_workspace_near_edge")
        if z < self.table_z + self.table_margin:
            risk_tags.append("low_object_height")

        if risk_tags:
            return ReachabilityRisk(
                object_x=x,
                object_y=y,
                object_z=z,
                risk_level="medium",
                risk_tags=risk_tags,
                recommended_approach="high_pregrasp",
                rationale=(
                    "Object is near a workspace edge; a higher pregrasp can "
                    "reduce the chance of an approach collision."
                ),
            )

        return ReachabilityRisk(
            object_x=x,
            object_y=y,
            object_z=z,
            risk_level="low",
            risk_tags=risk_tags,
            recommended_approach="direct_descend",
            rationale="Object is in the reachable workspace; direct approach is fine.",
        )
