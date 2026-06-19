"""Unit tests for object geometry adaptation."""

from __future__ import annotations

import pytest

from rosclaw_darwin.evaluation.object_geometry import (
    AdaptedPolicyParams,
    ObjectGeometry,
    ObjectGeometryAdapter,
    extract_geometry_from_config,
)


class TestObjectGeometry:
    def test_default_geometry(self):
        geom = ObjectGeometry()
        assert geom.extent == 0.05
        assert geom.girth == 0.05
        assert geom.volume == pytest.approx(0.05**3, rel=1e-6)

    def test_geometry_aggregates(self):
        geom = ObjectGeometry(width=0.04, depth=0.06, height=0.05)
        assert geom.extent == 0.06
        assert geom.girth == 0.04
        assert geom.radius == pytest.approx(0.5 * (0.04**2 + 0.06**2) ** 0.5, rel=1e-6)

    def test_to_from_dict_with_physics(self):
        geom = ObjectGeometry(
            width=0.1,
            depth=0.1,
            height=0.1,
            mass=0.5,
            static_friction=0.2,
        )
        data = geom.to_dict()
        restored = ObjectGeometry.from_dict(data)
        assert restored.mass == pytest.approx(0.5, abs=1e-6)
        assert restored.static_friction == pytest.approx(0.2, abs=1e-6)

    def test_mass_friction_aware_adaptation(self):
        adapter = ObjectGeometryAdapter()
        base_geom = ObjectGeometry(width=0.05, depth=0.05, height=0.05)
        base_params = adapter.adapt(base_geom)

        heavy_geom = ObjectGeometry(
            width=0.05, depth=0.05, height=0.05, mass=0.5, static_friction=0.2
        )
        heavy_params = adapter.adapt(heavy_geom)

        assert heavy_params.min_grasp_steps > base_params.min_grasp_steps
        assert heavy_params.gripper_close_threshold < base_params.gripper_close_threshold

    def test_mass_friction_ignored_when_none(self):
        adapter = ObjectGeometryAdapter()
        params = adapter.adapt(ObjectGeometry(width=0.05, depth=0.05, height=0.05))
        assert params.min_grasp_steps == 30
        assert params.gripper_close_threshold == pytest.approx(0.012, abs=1e-4)


class TestObjectGeometryAdapter:
    def test_default_cube_adaptation(self):
        adapter = ObjectGeometryAdapter()
        geom = ObjectGeometry(width=0.05, depth=0.05, height=0.05)
        params = adapter.adapt(geom)
        # Reference tuning matches the proven franka_ik_abs policy.
        assert params.grasp_dist_threshold == pytest.approx(0.04, abs=1e-4)
        assert params.grasp_z_tolerance == pytest.approx(0.005, abs=1e-4)
        assert params.approach_offset_z == pytest.approx(0.10, abs=1e-4)
        assert params.lift_height == pytest.approx(0.30, abs=1e-4)
        assert params.gripper_close_threshold == pytest.approx(0.012, abs=1e-4)
        assert params.min_grasp_steps == 30

    def test_larger_object_adaptation(self):
        adapter = ObjectGeometryAdapter()
        geom = ObjectGeometry(width=0.10, depth=0.10, height=0.10)
        params = adapter.adapt(geom)
        assert params.grasp_dist_threshold > 0.04
        assert params.grasp_z_tolerance > 0.005
        assert params.approach_offset_z == pytest.approx(0.15, abs=1e-4)
        assert params.lift_height == pytest.approx(0.35, abs=1e-4)
        assert params.min_grasp_steps >= 30

    def test_adaptation_clamps(self):
        adapter = ObjectGeometryAdapter()
        geom = ObjectGeometry(width=1.0, depth=1.0, height=1.0)
        params = adapter.adapt(geom)
        assert params.grasp_dist_threshold == adapter.max_grasp_dist_threshold
        assert params.grasp_z_tolerance == adapter.max_grasp_z_tolerance
        assert params.gripper_close_threshold == adapter.max_gripper_close_threshold


class TestExtractGeometryFromConfig:
    def test_size_list(self):
        geom = extract_geometry_from_config({"size": [0.1, 0.2, 0.3], "object_name": "box"})
        assert geom.width == 0.1
        assert geom.depth == 0.2
        assert geom.height == 0.3

    def test_dimensions_dict(self):
        geom = extract_geometry_from_config({"dimensions": {"width": 0.07, "depth": 0.08, "height": 0.09}})
        assert geom.width == 0.07
        assert geom.depth == 0.08
        assert geom.height == 0.09

    def test_empty_config(self):
        geom = extract_geometry_from_config({})
        assert geom.width == 0.05
        assert geom.object_name == "unknown"


class TestAdaptedPolicyParams:
    def test_to_dict(self):
        params = AdaptedPolicyParams(grasp_dist_threshold=0.04, lift_height=0.3)
        data = params.to_dict()
        assert data["grasp_dist_threshold"] == 0.04
        assert data["lift_height"] == 0.3
        assert "align_max_delta" in data
