"""Unit tests for object validity auditing."""

from rosclaw_darwin.evaluation.object_validity import ObjectValidityReport, check_object_validity


def test_valid_object_passes():
    report = check_object_validity(
        ObjectValidityReport(
            object_root_pos=[0.35, 0.0, 0.07],
            bbox_extent=[0.05, 0.05, 0.05],
            rigid_body_enabled=True,
            collision_enabled=True,
            object_above_table=True,
            table_contact_valid=True,
            metric_object_index=3,
            policy_object_index=3,
            trace_object_index=3,
        ),
        table_z=0.02,
    )
    assert report.valid
    assert not report.validity_errors


def test_object_z_out_of_bounds():
    report = check_object_validity(
        ObjectValidityReport(object_root_pos=[0.0, 0.0, -2496.0]),
        table_z=0.02,
    )
    assert not report.valid
    assert "object_z_out_of_bounds" in report.validity_errors


def test_invalid_bbox():
    report = check_object_validity(
        ObjectValidityReport(object_root_pos=[0.0, 0.0, 0.05], bbox_extent=[0.0, 0.05, 0.05]),
        table_z=0.02,
    )
    assert not report.valid
    assert "invalid_bbox" in report.validity_errors


def test_disabled_rigid_body_or_collision():
    report = check_object_validity(
        ObjectValidityReport(
            object_root_pos=[0.0, 0.0, 0.05],
            bbox_extent=[0.05, 0.05, 0.05],
            rigid_body_enabled=False,
            collision_enabled=True,
        ),
        table_z=0.02,
    )
    assert not report.valid
    assert "rigid_body_disabled" in report.validity_errors


def test_table_penetration():
    report = check_object_validity(
        ObjectValidityReport(
            object_root_pos=[0.0, 0.0, -0.01],
            bbox_extent=[0.05, 0.05, 0.05],
            rigid_body_enabled=True,
            collision_enabled=True,
            object_above_table=False,
        ),
        table_z=0.02,
    )
    assert not report.valid
    assert "table_penetration" in report.validity_errors


def test_object_index_mismatch():
    report = check_object_validity(
        ObjectValidityReport(
            object_root_pos=[0.0, 0.0, 0.05],
            bbox_extent=[0.05, 0.05, 0.05],
            rigid_body_enabled=True,
            collision_enabled=True,
            object_above_table=True,
            metric_object_index=3,
            policy_object_index=4,
            trace_object_index=3,
        ),
        table_z=0.02,
    )
    assert not report.valid
    assert "object_index_mismatch" in report.validity_errors
