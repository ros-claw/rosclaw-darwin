"""Object validity auditing for OOD / procedural fallback environments.

Before claiming that a policy fails on an out-of-distribution object, we must
first establish that the object itself is a valid rigid body with a reasonable
root pose, bounding box, enabled collision, and consistent metric/policy index.
This module provides a Pydantic schema and checker for that audit.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ObjectValidityReport(BaseModel):
    """Container-side + host-side object validity report."""

    task_id: str = "unknown"
    object_name: str = "unknown"
    valid: bool = False
    validity_errors: list[str] = Field(default_factory=list)
    validity_warnings: list[str] = Field(default_factory=list)
    object_root_pos: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    object_root_quat: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    bbox_extent: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    bbox_world_min: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    bbox_world_max: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rigid_body_enabled: bool = False
    collision_enabled: bool = False
    table_contact_valid: bool = False
    object_index_consistent: bool = False
    object_above_table: bool = False
    table_penetration_depth: float = 0.0
    linear_velocity: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    angular_velocity: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    mass: float | None = None
    static_friction: float | None = None
    dynamic_friction: float | None = None
    requested_object: str = "unknown"
    loaded_object: str = "unknown"
    metric_object_index: int | None = None
    policy_object_index: int | None = None
    trace_object_index: int | None = None
    step: int = 0
    seed: int | None = None


def check_object_validity(
    report: ObjectValidityReport,
    table_z: float = 0.18,
    table_penetration_threshold: float = 0.02,
    max_reasonable_pos: float = 10.0,
    max_bbox_extent: float = 1.0,
) -> ObjectValidityReport:
    """Populate ``valid`` and append errors/warnings according to v1.7 rules."""
    errors: list[str] = []
    warnings: list[str] = []

    x, y, z = report.object_root_pos
    if z < -0.1 or z > 2.0:
        errors.append("object_z_out_of_bounds")
    if abs(x) > max_reasonable_pos or abs(y) > max_reasonable_pos or abs(z) > max_reasonable_pos:
        errors.append("object_root_pose_unreasonable")

    ex, ey, ez = report.bbox_extent
    if ex <= 0 or ey <= 0 or ez <= 0 or ex > max_bbox_extent or ey > max_bbox_extent or ez > max_bbox_extent:
        errors.append("invalid_bbox")

    if not report.rigid_body_enabled:
        errors.append("rigid_body_disabled")
    if not report.collision_enabled:
        errors.append("collision_disabled")

    indices = [report.metric_object_index, report.policy_object_index, report.trace_object_index]
    non_none = [i for i in indices if i is not None]
    if non_none and len(set(non_none)) > 1:
        errors.append("object_index_mismatch")

    # Table contact / penetration.
    penetration = max(0.0, table_z - z)
    report.table_penetration_depth = round(penetration, 6)
    if penetration > table_penetration_threshold:
        errors.append("table_penetration")
    if not report.object_above_table:
        warnings.append("object_not_above_table")
    if not report.table_contact_valid and penetration <= table_penetration_threshold:
        warnings.append("table_contact_uncertain")

    report.valid = len(errors) == 0
    report.validity_errors = errors
    report.validity_warnings = warnings
    return report
