"""Object geometry capture and parameter adaptation for manipulation policies.

This module separates the "what is the object like" question from the policy
state machine so that grasp thresholds, lift heights, and approach offsets can
be scaled to the object that is actually loaded. It is intentionally free of
IsaacLab imports so it can run inside the Arena Docker container and in host
unit tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class ObjectGeometry:
    """Geometric properties of a manipulation target.

    Dimensions are expressed in metres.  ``extent`` is the largest side length,
    ``girth`` is the smallest horizontal side length, and ``radius`` is the
    half-extent of the circumscribed circle in the horizontal plane.  These
    aggregates are convenient for setting grasp tolerances and approach offsets.
    """

    width: float = 0.05
    depth: float = 0.05
    height: float = 0.05
    object_name: str = "unknown"
    asset_source: str = "unknown"

    # Optional physical properties for mass/friction-aware adaptation.
    mass: float | None = None
    static_friction: float | None = None

    # Optional raw data for diagnostics.
    raw_bounding_box: dict[str, Any] | None = None
    asset_path: str | None = None

    @property
    def extent(self) -> float:
        return max(self.width, self.depth, self.height)

    @property
    def girth(self) -> float:
        return min(self.width, self.depth)

    @property
    def radius(self) -> float:
        return 0.5 * math.hypot(self.width, self.depth)

    @property
    def volume(self) -> float:
        return self.width * self.depth * self.height

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "depth": self.depth,
            "height": self.height,
            "extent": self.extent,
            "girth": self.girth,
            "radius": self.radius,
            "volume": self.volume,
            "object_name": self.object_name,
            "asset_source": self.asset_source,
            "asset_path": self.asset_path,
            "mass": self.mass,
            "static_friction": self.static_friction,
            "raw_bounding_box": self.raw_bounding_box,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObjectGeometry":
        mass = data.get("mass")
        static_friction = data.get("static_friction")
        return cls(
            width=float(data.get("width", 0.05)),
            depth=float(data.get("depth", 0.05)),
            height=float(data.get("height", 0.05)),
            object_name=str(data.get("object_name", "unknown")),
            asset_source=str(data.get("asset_source", "unknown")),
            asset_path=data.get("asset_path"),
            mass=float(mass) if mass is not None else None,
            static_friction=float(static_friction) if static_friction is not None else None,
            raw_bounding_box=data.get("raw_bounding_box"),
        )


@dataclass
class AdaptedPolicyParams:
    """Policy parameters scaled to an object's geometry.

    The defaults correspond to the historical dex_cube (0.05 m cube) tuning.
    """

    grasp_dist_threshold: float = 0.03
    grasp_z_tolerance: float = 0.02
    approach_offset_z: float = 0.08
    lift_height: float = 0.25
    gripper_close_threshold: float = 0.03
    min_grasp_steps: int = 15
    object_following_distance_threshold: float = 0.10
    align_max_delta: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "grasp_dist_threshold": self.grasp_dist_threshold,
            "grasp_z_tolerance": self.grasp_z_tolerance,
            "approach_offset_z": self.approach_offset_z,
            "lift_height": self.lift_height,
            "gripper_close_threshold": self.gripper_close_threshold,
            "min_grasp_steps": self.min_grasp_steps,
            "object_following_distance_threshold": self.object_following_distance_threshold,
            "align_max_delta": self.align_max_delta,
        }


@dataclass
class ObjectGeometryAdapter:
    """Adapts heuristic policy parameters to the geometry of the loaded object.

    The base tuning assumes a 0.05 m dex_cube.  For objects with a different
    horizontal extent we scale the position tolerances so that the policy does
    not demand sub-millimetre precision for large objects (which is unnecessary
    and brittle) or overshoot small objects.  Lift height and approach offset
    are scaled so the gripper clears the object by a roughly constant margin.
    """

    # Tuning reference: dex_cube side length [m].
    reference_extent: float = 0.05
    # Tuning reference: dex_cube height [m].
    reference_height: float = 0.05

    # Scale tolerances linearly with extent/height, but clamp to sane limits.
    # Reference values are taken from the proven franka_ik_abs goal_pose policy
    # (configs/policies/heuristic_servo_goal_pose_abs.yaml) so that a 0.05 m
    # dex_cube gets the exact tuning that achieved 20/20 success.
    min_grasp_dist_threshold: float = 0.015
    max_grasp_dist_threshold: float = 0.08
    min_grasp_z_tolerance: float = 0.003
    max_grasp_z_tolerance: float = 0.02

    # Approach offset is object top + margin so the gripper clears the object
    # before descending. 0.05 m margin matches the abs policy (0.10 m for cube).
    approach_offset_margin: float = 0.05
    lift_height_margin: float = 0.25

    # Gripper close threshold is not scaled much; keep within empirically
    # calibrated range (blocked close ~0.024 m).
    min_gripper_close_threshold: float = 0.008
    max_gripper_close_threshold: float = 0.04

    # Mass/friction-aware tuning.  These are only applied when the scene/parser
    # actually provides mass/static_friction; otherwise geometry-only adaptation
    # behaves exactly as before (non-regression on dex_cube).
    reference_mass: float = 0.05
    heavy_mass_threshold: float = 0.15
    low_friction_threshold: float = 0.35
    mass_grasp_step_factor: float = 30.0

    def adapt(self, geometry: ObjectGeometry) -> AdaptedPolicyParams:
        """Return policy parameters scaled to ``geometry``."""
        extent_ratio = max(0.1, geometry.extent / max(1e-6, self.reference_extent))
        height_ratio = max(0.1, geometry.height / max(1e-6, self.reference_height))

        grasp_dist = self._clamp(
            0.04 * extent_ratio,
            self.min_grasp_dist_threshold,
            self.max_grasp_dist_threshold,
        )
        grasp_z = self._clamp(
            0.005 * height_ratio,
            self.min_grasp_z_tolerance,
            self.max_grasp_z_tolerance,
        )
        approach_offset = geometry.height + self.approach_offset_margin
        lift_height = geometry.height + self.lift_height_margin

        # Gripper close threshold grows slightly with girth so the fingers do
        # not have to close to an impossible gap for thick objects. Reference
        # value 0.012 m matches the abs policy.
        gripper_close = self._clamp(
            0.012 + 0.5 * max(0.0, geometry.girth - self.reference_extent),
            self.min_gripper_close_threshold,
            self.max_gripper_close_threshold,
        )

        # Allow more time to close on larger objects. Reference 30 steps.
        min_grasp_steps = max(10, int(30 + 10 * (extent_ratio - 1.0)))

        # Mass/friction-aware overrides.  Heavier objects need a tighter, longer
        # squeeze; low-friction objects need more grip force to avoid slip.
        if geometry.mass is not None and geometry.mass > self.heavy_mass_threshold:
            mass_excess = geometry.mass - self.heavy_mass_threshold
            min_grasp_steps += int(self.mass_grasp_step_factor * mass_excess)
            gripper_close = max(
                self.min_gripper_close_threshold,
                gripper_close * 0.85,
            )
        if geometry.static_friction is not None and geometry.static_friction < self.low_friction_threshold:
            min_grasp_steps += 5
            gripper_close = max(
                self.min_gripper_close_threshold,
                gripper_close * 0.85,
            )

        # Object-following verification window: larger objects tolerate slightly
        # more relative motion, but keep it bounded.
        following_threshold = self._clamp(
            0.10 * extent_ratio,
            0.06,
            0.16,
        )

        # Align speed is reduced for tall/extent objects to avoid toppling.
        align_max_delta = self._clamp(
            0.06 / max(1.0, extent_ratio),
            0.02,
            0.08,
        )

        return AdaptedPolicyParams(
            grasp_dist_threshold=round(grasp_dist, 4),
            grasp_z_tolerance=round(grasp_z, 4),
            approach_offset_z=round(approach_offset, 4),
            lift_height=round(lift_height, 4),
            gripper_close_threshold=round(gripper_close, 4),
            min_grasp_steps=min_grasp_steps,
            object_following_distance_threshold=round(following_threshold, 4),
            align_max_delta=round(align_max_delta, 4),
        )

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))


def extract_geometry_from_config(config: dict[str, Any]) -> ObjectGeometry:
    """Build geometry from a task/physics_ablation config block.

    Recognises ``size: [x, y, z]`` or ``dimensions: {width, depth, height}``.
    """
    size = config.get("size")
    if size is not None:
        if isinstance(size, (list, tuple)) and len(size) >= 3:
            return ObjectGeometry(
                width=float(size[0]),
                depth=float(size[1]),
                height=float(size[2]),
                object_name=str(config.get("object_name", "unknown")),
                asset_source=str(config.get("asset_source", "config")),
                asset_path=config.get("asset_path"),
            )

    dims = config.get("dimensions") or config.get("geometry") or {}
    if dims:
        return ObjectGeometry(
            width=float(dims.get("width", 0.05)),
            depth=float(dims.get("depth", 0.05)),
            height=float(dims.get("height", 0.05)),
            object_name=str(config.get("object_name", "unknown")),
            asset_source=str(config.get("asset_source", "config")),
            asset_path=config.get("asset_path"),
        )

    return ObjectGeometry(
        object_name=str(config.get("object_name", "unknown")),
        asset_source="config_default",
    )


def extract_geometry_from_scene(scene: Any, object_name: str = "unknown") -> ObjectGeometry:
    """Extract object geometry from an IsaacLab/Arena scene object.

    This runs inside the Arena process where ``scene`` is the environment scene.
    It tries a few common attribute paths and falls back to defaults so that a
    missing attribute does not crash the policy.
    """
    geometry = ObjectGeometry(object_name=object_name, asset_source="scene")

    try:
        # Look for the object by name or common aliases.
        obj = None
        for key in scene.keys():
            if str(key) == object_name or str(key) in {"dex_cube", "object", "cube", "procedural_cube"}:
                candidate = scene[key]
                cand_name = getattr(candidate, "name", str(key))
                if cand_name == object_name or object_name == "unknown":
                    obj = candidate
                    break

        if obj is None:
            return geometry

        # Try to read a spawn size attribute (procedural cube convention).
        spawn = getattr(obj, "spawn", None)
        if spawn is not None:
            size = getattr(spawn, "size", None)
            if size is not None:
                s = _as_tuple(size)
                if len(s) >= 3:
                    geometry.width = float(s[0])
                    geometry.depth = float(s[1])
                    geometry.height = float(s[2])
                    return geometry
            scale = getattr(spawn, "scale", None)
            if scale is not None:
                sc = _as_tuple(scale)
                geometry.width *= float(sc[0]) if len(sc) > 0 else 1.0
                geometry.depth *= float(sc[1]) if len(sc) > 1 else 1.0
                geometry.height *= float(sc[2]) if len(sc) > 2 else 1.0

        # Try to read physical properties from the spawn config or the object.
        try:
            if spawn is not None:
                mass_props = getattr(spawn, "mass_props", None)
                if mass_props is not None:
                    mass = getattr(mass_props, "mass", None)
                    if mass is not None:
                        geometry.mass = float(mass)
                physics_material = getattr(spawn, "physics_material", None)
                if physics_material is not None:
                    static_friction = getattr(physics_material, "static_friction", None)
                    if static_friction is not None:
                        geometry.static_friction = float(static_friction)
            if geometry.mass is None and hasattr(obj, "data"):
                mass = getattr(obj.data, "default_mass", None)
                if mass is None:
                    mass = getattr(obj.data, "mass", None)
                if mass is not None:
                    geometry.mass = float(mass)
            if geometry.static_friction is None and hasattr(obj, "data"):
                static_friction = getattr(obj.data, "static_friction", None)
                if static_friction is not None:
                    geometry.static_friction = float(static_friction)
        except Exception:
            pass

        # Try bounding box if available.
        bbox = None
        if hasattr(obj, "get_bounding_box"):
            try:
                bbox = obj.get_bounding_box()
            except Exception:
                bbox = None
        if bbox is not None:
            # AxisAlignedBoundingBox has upper/lower attributes.
            upper = getattr(bbox, "upper", None)
            lower = getattr(bbox, "lower", None)
            if upper is not None and lower is not None:
                upper = _as_tuple(upper)
                lower = _as_tuple(lower)
                if len(upper) >= 3 and len(lower) >= 3:
                    geometry.width = float(upper[0] - lower[0])
                    geometry.depth = float(upper[1] - lower[1])
                    geometry.height = float(upper[2] - lower[2])
                    geometry.raw_bounding_box = {
                        "upper": list(upper),
                        "lower": list(lower),
                    }
                    return geometry
    except Exception:
        pass

    return geometry


def _as_tuple(value: Any) -> tuple[float, ...]:
    """Normalise a scalar/list/tensor to a tuple of floats."""
    if isinstance(value, (list, tuple)):
        return tuple(float(v) for v in value)
    try:
        import torch

        if isinstance(value, torch.Tensor):
            return tuple(float(v) for v in value.flatten().tolist())
    except Exception:
        pass
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return tuple(float(v) for v in value.flatten().tolist())
    except Exception:
        pass
    return (float(value),)
