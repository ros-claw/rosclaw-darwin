# Heuristic lift policy for Arena Docker evaluation.
# Uses delta pose control (Franka IK relative mode, scale=0.5).
# Called dynamically by eval_runner via policy_type module path.

import argparse
import json
import math
import os
import sys
import types
from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import torch
from gymnasium.spaces.dict import Dict as GymSpacesDict

try:
    from rosclaw_darwin.evaluation.object_geometry import (
        AdaptedPolicyParams,
        ObjectGeometry,
        ObjectGeometryAdapter,
        extract_geometry_from_config,
        extract_geometry_from_scene,
    )
    from rosclaw_darwin.evaluation.reachability import (
        ReachabilityRiskEstimator,
    )
except Exception:
    # Container-side fallback: the host module is not mounted into the Docker
    # container.  Provide a minimal inlined implementation so geometry adaptation
    # still works without the full rosclaw_darwin package.
    @dataclass
    class _ObjectGeometry:
        width: float = 0.05
        depth: float = 0.05
        height: float = 0.05
        object_name: str = "unknown"
        asset_source: str = "unknown"
        asset_path: str | None = None
        raw_bounding_box: dict[str, Any] | None = None
        mass: float | None = None
        static_friction: float | None = None

        @property
        def extent(self) -> float:
            return max(self.width, self.depth, self.height)

        @property
        def girth(self) -> float:
            return min(self.width, self.depth)

    @dataclass
    class _AdaptedPolicyParams:
        grasp_dist_threshold: float = 0.03
        grasp_z_tolerance: float = 0.02
        approach_offset_z: float = 0.08
        lift_height: float = 0.25
        gripper_close_threshold: float = 0.03
        min_grasp_steps: int = 15
        object_following_distance_threshold: float = 0.10
        align_max_delta: float | None = None

    class _ObjectGeometryAdapter:
        reference_extent: float = 0.05
        reference_height: float = 0.05
        min_grasp_dist_threshold: float = 0.015
        max_grasp_dist_threshold: float = 0.08
        min_grasp_z_tolerance: float = 0.003
        max_grasp_z_tolerance: float = 0.02
        approach_offset_margin: float = 0.05
        lift_height_margin: float = 0.25
        min_gripper_close_threshold: float = 0.008
        max_gripper_close_threshold: float = 0.04
        reference_mass: float = 0.05
        heavy_mass_threshold: float = 0.15
        low_friction_threshold: float = 0.35
        mass_grasp_step_factor: float = 30.0

        @staticmethod
        def _clamp(value: float, low: float, high: float) -> float:
            return max(low, min(high, value))

        def adapt(self, geometry: Any) -> "_AdaptedPolicyParams":
            extent_ratio = max(0.1, geometry.extent / max(1e-6, self.reference_extent))
            height_ratio = max(0.1, geometry.height / max(1e-6, self.reference_height))
            grasp_dist = self._clamp(0.04 * extent_ratio, self.min_grasp_dist_threshold, self.max_grasp_dist_threshold)
            grasp_z = self._clamp(0.005 * height_ratio, self.min_grasp_z_tolerance, self.max_grasp_z_tolerance)
            approach_offset = geometry.height + self.approach_offset_margin
            lift_height = geometry.height + self.lift_height_margin
            gripper_close = self._clamp(
                0.012 + 0.5 * max(0.0, geometry.girth - self.reference_extent),
                self.min_gripper_close_threshold,
                self.max_gripper_close_threshold,
            )
            min_grasp_steps = max(10, int(30 + 10 * (extent_ratio - 1.0)))
            if getattr(geometry, "mass", None) is not None and geometry.mass > self.heavy_mass_threshold:
                mass_excess = geometry.mass - self.heavy_mass_threshold
                min_grasp_steps += int(self.mass_grasp_step_factor * mass_excess)
                gripper_close = max(self.min_gripper_close_threshold, gripper_close * 0.85)
            if getattr(geometry, "static_friction", None) is not None and geometry.static_friction < self.low_friction_threshold:
                min_grasp_steps += 5
                gripper_close = max(self.min_gripper_close_threshold, gripper_close * 0.85)
            following_threshold = self._clamp(0.10 * extent_ratio, 0.06, 0.16)
            align_max_delta = self._clamp(0.06 / max(1.0, extent_ratio), 0.02, 0.08)
            return _AdaptedPolicyParams(
                grasp_dist_threshold=round(grasp_dist, 4),
                grasp_z_tolerance=round(grasp_z, 4),
                approach_offset_z=round(approach_offset, 4),
                lift_height=round(lift_height, 4),
                gripper_close_threshold=round(gripper_close, 4),
                min_grasp_steps=min_grasp_steps,
                object_following_distance_threshold=round(following_threshold, 4),
                align_max_delta=round(align_max_delta, 4),
            )

    def _extract_geometry_from_config(config: dict[str, Any]) -> "_ObjectGeometry":
        size = config.get("size")
        if isinstance(size, (list, tuple)) and len(size) >= 3:
            return _ObjectGeometry(
                width=float(size[0]), depth=float(size[1]), height=float(size[2]),
                object_name=str(config.get("object_name", "unknown")),
                asset_source=str(config.get("asset_source", "config")),
                asset_path=config.get("asset_path"),
            )
        dims = config.get("dimensions") or config.get("geometry") or {}
        if dims:
            return _ObjectGeometry(
                width=float(dims.get("width", 0.05)),
                depth=float(dims.get("depth", 0.05)),
                height=float(dims.get("height", 0.05)),
                object_name=str(config.get("object_name", "unknown")),
                asset_source=str(config.get("asset_source", "config")),
                asset_path=config.get("asset_path"),
            )
        return _ObjectGeometry(object_name=str(config.get("object_name", "unknown")), asset_source="config_default")

    def _extract_geometry_from_scene(scene: Any, object_name: str = "unknown") -> "_ObjectGeometry":
        geometry = _ObjectGeometry(object_name=object_name, asset_source="scene")
        try:
            obj = None
            for key in scene.keys():
                if str(key) == object_name or str(key) in {"dex_cube", "object", "cube", "procedural_cube"}:
                    candidate = scene[key]
                    cand_name = getattr(candidate, "name", str(key))
                    if cand_name == object_name or object_name == "unknown":
                        obj = candidate
                        geometry.object_name = str(key)
                        break
            if obj is None:
                return geometry
            spawn = getattr(obj, "spawn", None)
            if spawn is not None:
                size = getattr(spawn, "size", None)
                if size is not None:
                    s = tuple(float(v) for v in size) if isinstance(size, (list, tuple)) else (float(size),)
                    if len(s) >= 3:
                        geometry.width = float(s[0])
                        geometry.depth = float(s[1])
                        geometry.height = float(s[2])
                        return geometry
                scale = getattr(spawn, "scale", None)
                if scale is not None:
                    sc = tuple(float(v) for v in scale) if isinstance(scale, (list, tuple)) else (float(scale),)
                    geometry.width *= float(sc[0]) if len(sc) > 0 else 1.0
                    geometry.depth *= float(sc[1]) if len(sc) > 1 else 1.0
                    geometry.height *= float(sc[2]) if len(sc) > 2 else 1.0
                # Read physical properties from the spawn config if available.
                try:
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
                except Exception:
                    pass
            bbox = None
            if hasattr(obj, "get_bounding_box"):
                try:
                    bbox = obj.get_bounding_box()
                except Exception:
                    bbox = None
            if bbox is not None:
                upper = getattr(bbox, "upper", None)
                lower = getattr(bbox, "lower", None)
                if upper is not None and lower is not None:
                    upper = tuple(float(v) for v in upper) if isinstance(upper, (list, tuple)) else (float(upper),)
                    lower = tuple(float(v) for v in lower) if isinstance(lower, (list, tuple)) else (float(lower),)
                    if len(upper) >= 3 and len(lower) >= 3:
                        geometry.width = float(upper[0] - lower[0])
                        geometry.depth = float(upper[1] - lower[1])
                        geometry.height = float(upper[2] - lower[2])
                        geometry.raw_bounding_box = {"upper": list(upper), "lower": list(lower)}
                        return geometry
        except Exception:
            pass
        return geometry

    class _ReachabilityRiskEstimator:
        """Container-side fallback mirroring the host ReachabilityRiskEstimator.

        The host module may not be importable inside the Docker container, so we
        duplicate the lightweight kinematic-free risk logic here.  This keeps the
        reachability-aware approach planner functional in containerized Arena runs.
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
            robot_base_pos: Any = None,
            object_yaw: float | None = None,
            **kwargs: Any,
        ) -> Any:
            x, y, z = object_pos
            risk_tags: list[str] = []

            # Only flag positive-y as a risk when yaw is positive or unknown.
            # Positive-y + negative yaw is not part of the corner-collision cluster.
            yaw_positive = object_yaw is None or object_yaw > self.positive_yaw_threshold
            if y > self.positive_y_threshold and yaw_positive:
                risk_tags.append("positive_y_workspace_edge")
                risk_tags.append("positive_yaw_corner_collision")
                return types.SimpleNamespace(
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

            if y < self.negative_y_threshold:
                risk_tags.append("negative_y_workspace_edge")
            if x < self.min_reachable_x:
                risk_tags.append("x_workspace_far_edge")
            if x > self.max_reachable_x:
                risk_tags.append("x_workspace_near_edge")
            if z < self.table_z + self.table_margin:
                risk_tags.append("low_object_height")

            if risk_tags:
                return types.SimpleNamespace(
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

            return types.SimpleNamespace(
                object_x=x,
                object_y=y,
                object_z=z,
                risk_level="low",
                risk_tags=risk_tags,
                recommended_approach="direct_descend",
                rationale="Object is in the reachable workspace; direct approach is fine.",
            )

    ObjectGeometry = _ObjectGeometry  # type: ignore[misc,assignment]
    ObjectGeometryAdapter = _ObjectGeometryAdapter  # type: ignore[misc,assignment]
    AdaptedPolicyParams = _AdaptedPolicyParams  # type: ignore[misc,assignment]
    extract_geometry_from_config = _extract_geometry_from_config  # type: ignore[misc,assignment]
    extract_geometry_from_scene = _extract_geometry_from_scene  # type: ignore[misc,assignment]
    ReachabilityRiskEstimator = _ReachabilityRiskEstimator  # type: ignore[misc,assignment]

try:
    from isaaclab_arena.policy.policy_base import PolicyBase
except Exception:  # pragma: no cover - host side does not have IsaacLab-Arena installed
    class PolicyBase:
        """Minimal stub so the policy file can be imported in host tests."""

        def __init__(self, config):
            self.config = config
except Exception:  # pragma: no cover - host side does not have IsaacLab-Arena installed
    class PolicyBase:
        """Minimal stub so the policy file can be imported in host tests."""

        def __init__(self, config):
            self.config = config


_TRACE_DIR = os.environ.get("ROSCLAW_TRACE_DIR", "/workspace/data/traces")
_TRACE_PATH = os.path.join(_TRACE_DIR, "episode_trace.jsonl")

# Ensure the trace directory exists (host bind mount may not create it).
try:
    os.makedirs(_TRACE_DIR, exist_ok=True)
except Exception:
    pass


def _append_trace(step: dict[str, Any]) -> None:
    """Append a scalar step record to the shared trace file.

    The trace is read by ``run_eval.py`` to compute per-episode progress metrics.
    When ``step["step"] == 0`` the file is truncated so each new episode starts
    with a clean trace, even if a previous container left a root-owned file
    behind.
    """
    try:
        mode = "w" if step.get("step") == 0 else "a"
        with open(_TRACE_PATH, mode, encoding="utf-8") as f:
            f.write(json.dumps(step) + "\n")
    except Exception as e:
        import sys
        print(f"[TRACE_WRITE_ERROR] {e}", file=sys.stderr)
        pass


def _angle_diff(target: float, current: float) -> float:
    """Smallest signed angle from current to target, wrapped to [-pi, pi]."""
    diff = target - current
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return diff


def _randomize_object_pose_from_seed(env: Any, seed: int) -> None:
    """Best-effort seed-driven object pose randomization inside the policy.

    Arena's object placer ignores the forwarded seed for some environments, so
    we perturb the object's root state once at the first policy step.  This
    keeps the randomization reproducible (same seed → same perturbation) and
    visible in the episode trace.
    """
    try:
        import random

        rng = random.Random(seed)
        scene = getattr(env, "unwrapped", env).scene
        object_names = {"dex_cube", "object", "cube", "procedural_cube"}
        for key in scene.keys():
            name = str(key)
            if name not in object_names:
                continue
            obj = scene[key]
            if not hasattr(obj, "data") or not hasattr(obj.data, "root_state_w"):
                continue
            try:
                dx = rng.uniform(-0.03, 0.03)
                dy = rng.uniform(-0.03, 0.03)
                yaw = rng.uniform(-math.radians(30.0), math.radians(30.0))
                half_yaw = yaw / 2.0
                quat = torch.tensor(
                    [0.0, 0.0, math.sin(half_yaw), math.cos(half_yaw)],
                    dtype=obj.data.root_state_w.dtype,
                    device=obj.data.root_state_w.device,
                )
                # Perturb around the current reset pose; do not hardcode world
                # coordinates because root_state_w may be in a different frame.
                current_pos = obj.data.root_state_w[0, :3].clone()
                current_pos[0] += dx
                current_pos[1] += dy
                obj.data.root_state_w[0, :3] = current_pos
                obj.data.root_state_w[0, 3:7] = quat
                obj.data.root_state_w[0, 7:] = 0.0
                if hasattr(obj, "write_root_state_to_sim"):
                    obj.write_root_state_to_sim(obj.data.root_state_w)
                print(
                    f"[POLICY_SEED_RANDOMIZATION] {name}: dx={dx:.4f} dy={dy:.4f} "
                    f"yaw={math.degrees(yaw):.1f}deg",
                    file=sys.stderr,
                )
                sys.stderr.flush()
            except Exception as exc:
                print(
                    f"[POLICY_SEED_RANDOMIZATION] failed for {name}: {exc}",
                    file=sys.stderr,
                )
                sys.stderr.flush()
    except Exception as exc:
        print(f"[POLICY_SEED_RANDOMIZATION] failed: {exc}", file=sys.stderr)
        sys.stderr.flush()


def _quat_to_yaw(q: torch.Tensor) -> float:
    """Yaw angle from a quaternion in Arena's (x, y, z, w) ordering."""
    x, y, z, w = q[0].item(), q[1].item(), q[2].item(), q[3].item()
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _quat_to_rpy(q: torch.Tensor) -> tuple[float, float, float]:
    """Roll/pitch/yaw from a quaternion in Arena's (x, y, z, w) ordering."""
    x, y, z, w = q[0].item(), q[1].item(), q[2].item(), q[3].item()
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


_TRACE_METADATA_WRITTEN = False


def _write_trace_metadata(metadata: dict[str, Any] | None = None) -> None:
    """Write a one-off metadata file next to the trace.

    This records schema version and field definitions so downstream analysis
    knows whether ``orientation_error`` means object-yaw-error or
    end-effector-yaw-error.
    """
    global _TRACE_METADATA_WRITTEN
    if _TRACE_METADATA_WRITTEN:
        return
    _TRACE_METADATA_WRITTEN = True
    try:
        meta_path = os.path.join(_TRACE_DIR, "trace_metadata.json")
        payload = {
            "trace_schema_version": "goal_pose_trace_v2",
            "orientation_error_definition": "object_yaw_error_to_target_yaw",
            "eef_yaw_recorded": True,
        }
        if metadata:
            payload.update(metadata)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        import sys

        print(f"[TRACE_METADATA_ERROR] {e}", file=sys.stderr)
        pass


@dataclass
class HeuristicLiftPolicyArgs:
    """Configuration for HeuristicLiftPolicy."""

    skill_hints: list[str] | None = None

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoLiftPolicyArgs:
    """Configuration for HeuristicServoLiftPolicy."""

    skill_hints: list[str] | None = None
    approach_offset_z: float = 0.08
    grasp_offset_z: float = 0.0
    lift_height: float = 0.25
    kp: float = 5.0
    grasp_dist_threshold: float = 0.03
    gripper_close_threshold: float = 0.03
    min_grasp_steps: int = 15
    approach_horizontal_threshold: float = 0.05
    max_state_steps: int = 300
    success_threshold: float = 0.05
    grasp_squeeze_steps: int = 0
    lift_max_delta: float | None = None

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoPickPolicyArgs(HeuristicServoLiftPolicyArgs):
    """Configuration for HeuristicServoPickPolicy.

    Adds explicit post-lift alignment and hold phases for pick/place-style
    tasks where the object must be positioned at a command target and held.
    """

    enable_align_phase: bool = True
    align_kp: float = 0.6
    final_align_speed: float = 0.4
    hold_steps: int = 20
    align_height_offset: float = 0.0
    settle_before_success: bool = True
    near_target_gain: float = 0.5
    align_max_delta: float | None = 0.06
    slow_align_max_delta: float | None = 0.03
    align_horizontal_scale: float = 1.0
    slow_align_threshold: float = 0.05

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoPickPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoLiftPolicyArgs:
    """Configuration for HeuristicServoLiftPolicy."""

    skill_hints: list[str] | None = None
    approach_offset_z: float = 0.08
    grasp_offset_z: float = 0.0
    lift_height: float = 0.25
    kp: float = 5.0
    grasp_dist_threshold: float = 0.03
    gripper_close_threshold: float = 0.03
    min_grasp_steps: int = 15
    approach_horizontal_threshold: float = 0.05
    max_state_steps: int = 300
    success_threshold: float = 0.05
    grasp_squeeze_steps: int = 0
    lift_max_delta: float | None = None

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoLiftPolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


@dataclass
class HeuristicServoGoalPosePolicyArgs(HeuristicServoLiftPolicyArgs):
    """Configuration for HeuristicServoGoalPosePolicy.

    Extends the lift servo args with placement/release behaviour needed for
    goal-pose / pick-and-place tasks.
    """

    min_release_steps: int = 10
    align_height_offset: float = 0.0
    orientation_threshold: float = 1.0
    lift_horizontal_scale: float = 0.9
    lift_kp_multiplier: float = 1.0
    lift_max_delta: float | None = None
    align_horizontal_scale: float = 1.0
    align_kp_multiplier: float = 1.0
    align_max_delta: float | None = None
    grasp_z_tolerance: float = 0.02
    fixed_target_pos: list[float] | None = None
    fixed_target_quat: list[float] | None = None
    release_at_target: bool = False
    require_orientation_alignment: bool = False

    # Grasp-stability v2 controls.
    pre_grasp_orient: bool = True
    grasp_target_yaw_offset: float = 0.0
    pre_grasp_yaw_threshold: float = 0.2
    reorient_before_align: bool = True
    reorient_height_offset: float = 0.05
    max_lift_delta_z: float = 0.08

    # Optional continuous yaw alignment during APPROACH.  This rotates the
    # gripper toward object_yaw + approach_yaw_offset while the arm is still
    # above the object, which can avoid kinematic dead-ends for seeds where the
    # default gripper yaw makes the target unreachable.
    align_yaw_during_approach: bool = False
    # Yaw offset relative to object_yaw used during the approach alignment.
    # The default pi keeps the same gripper-object relative orientation as the
    # reset pose, so reorientation to the environment's target_quat remains valid.
    approach_yaw_offset: float = math.pi

    # v3 intervention controls.
    verify_object_following_steps: int = 0
    object_following_distance_threshold: float = 0.10
    use_quaternion_orientation_target: bool = False
    yaw_step_size: float = 0.20
    stabilize_steps_after_yaw: int = 0
    skip_broken_yaw_control: bool = False

    # Object-geometry adaptation (Sprint 4).
    use_object_geometry_adaptation: bool = False
    object_geometry: dict[str, Any] | None = None

    # Reachability-aware approach planner (Sprint 1 v1.6).
    reachability_strategy: str = "direct_descend"
    reachability_risk_estimator: bool = False
    positive_y_workspace_risk: bool = False
    reachability_positive_y_threshold: float = 0.01
    reachability_positive_yaw_threshold: float = 0.0
    high_pregrasp_z_offset: float = 0.25
    side_pregrasp_y_offset: float = -0.05
    side_pregrasp_z_offset: float = 0.15

    # Pre-grasp yaw alignment v2 (Sprint 2 v1.6).
    pre_grasp_yaw_align_v2: bool = False
    pre_grasp_yaw_strategy: str = "target_yaw_before_grasp"
    pre_grasp_yaw_fraction: float = 0.8
    pre_grasp_yaw_max_step: float = 0.2
    pre_grasp_yaw_settle_steps: int = 3
    pre_grasp_yaw_safety_distance: float = 0.04
    post_grasp_yaw_residual_fraction: float = 0.2

    # Structural FailureToHint v3.1 regrasp controls (Sprint 4 v1.6).
    enable_regrasp: bool = False
    structural_regrasp: bool = False
    max_regrasp_attempts: int = 0
    regrasp_xy_offsets: list[list[float]] | None = None
    verify_lift_response_steps: int = 0
    min_lift_response_z: float = 0.01

    # Optional world-frame target yaw override (radians).  The Arena
    # cube_goal_pose environment currently fixes target_yaw to pi/2 for all
    # seeds, so this parameter lets us diagnose cross-orientation
    # generalization by forcing the policy to align the object to a different
    # yaw while keeping the same asset and initial pose distribution.
    target_yaw_override: float | None = None

    # Large-yaw targeted intervention strategies (Sprint 5 v1.7).
    # These are intentionally structural strategy switches rather than a new
    # state machine: they re-parameterise the existing PRE_GRASP_YAW_ALIGN /
    # REORIENT phases to test whether the large-yaw failure is a coupling /
    # torsional-slip problem or an in-hand-reorientation problem.
    large_yaw_strategy: str | None = None  # "grasp_at_target_yaw" | "low_height_incremental_yaw"
    disable_inhand_reorient: bool = False
    lift_height_before_yaw: float = 0.05

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "HeuristicServoGoalPosePolicyArgs":
        return cls(skill_hints=getattr(args, "skill_hints", None))


class HeuristicLiftPolicy(PolicyBase):
    """Fixed-sequence heuristic policy for lift_object with delta IK control.

    Action mapping for FrankaIK relative mode (scale=0.5):
      action[:3]  = delta position  (actual delta = action * 0.5)
      action[3:7] = delta quaternion (actual delta = action * 0.5)
      action[7]   = gripper command
    """

    name = "heuristic_lift"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._skill_hints = set((config.skill_hints or []))
        # Skill hints adapt the heuristic parameters.
        self._delta_z = 0.04
        self._descent_steps = 30
        self._gripper_close_steps = 10
        self._lift_steps = 40
        if "efficient_execution" in self._skill_hints:
            self._delta_z *= 1.5
        if "grasp_adjust" in self._skill_hints:
            self._gripper_close_steps += 5
        if "adaptive_skill" in self._skill_hints:
            self._descent_steps = max(10, self._descent_steps - 5)
            self._lift_steps += 10

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)

        step = self._step
        self._step += 1

        # Log skill hint consumption once for observability.
        if step == 0 and self._skill_hints:
            import sys
            print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
            print(f"[HEURISTIC_SKILL_HINTS] params: delta_z={self._delta_z:.4f} "
                  f"descent={self._descent_steps} close={self._gripper_close_steps} lift={self._lift_steps}", file=sys.stderr)
            sys.stderr.flush()

        # Delta per step (will be multiplied by scale=0.5 inside controller)
        delta_z = self._delta_z

        descent_end = self._descent_steps
        close_end = descent_end + self._gripper_close_steps
        lift_end = close_end + self._lift_steps

        if step < descent_end:
            # Phase 1: descend toward object
            action[..., 2] = -delta_z
            action[..., -1] = 1.0   # gripper open
        elif step < close_end:
            # Phase 2: close gripper at object height
            action[..., 2] = 0.0
            action[..., -1] = -1.0  # gripper close
        elif step < lift_end:
            # Phase 3: lift up
            action[..., 2] = delta_z
            action[..., -1] = -1.0  # gripper close
        else:
            # Phase 4: hold
            action[..., 2] = 0.0
            action[..., -1] = -1.0

        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicLiftPolicy":
        return HeuristicLiftPolicy(HeuristicLiftPolicyArgs.from_cli_args(args))


class HeuristicServoLiftPolicy(PolicyBase):
    """Closed-loop servo heuristic for lift_object using observations.

    Reads eef_pos / eef_quat / object_pos / gripper_pos / task_obs target
    from the environment to servo above the object, descend, close the
    gripper, and lift toward the command target. Works with both 7-dim and
    8-dim action spaces and adapts to relative or absolute IK controllers.
    """

    name = "heuristic_servo_lift"
    config_class = HeuristicServoLiftPolicyArgs

    def __init__(self, config: HeuristicServoLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._state = "APPROACH"
        self._state_step = 0
        self._skill_hints = set(config.skill_hints or [])
        self._relative_mode: bool | None = None
        self._action_scale: float = 1.0
        self._episode_idx = 0

        # Clear any trace from a previous job in the same container.
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

        self._approach_offset_z = config.approach_offset_z
        self._grasp_offset_z = config.grasp_offset_z
        self._lift_height = config.lift_height
        self._kp = config.kp
        self._grasp_dist_threshold = config.grasp_dist_threshold
        self._gripper_close_threshold = config.gripper_close_threshold
        self._min_grasp_steps = config.min_grasp_steps
        self._approach_horizontal_threshold = config.approach_horizontal_threshold
        self._max_state_steps = config.max_state_steps
        self._success_threshold = config.success_threshold
        self._lift_kp_multiplier = getattr(config, "lift_kp_multiplier", 1.0)
        self._lift_horizontal_scale = getattr(config, "lift_horizontal_scale", 0.6)
        self._grasp_squeeze_steps = getattr(config, "grasp_squeeze_steps", 0)
        self._lift_max_delta = getattr(config, "lift_max_delta", None)

        if "longer_gripper_close" in self._skill_hints:
            self._min_grasp_steps += 5
            self._grasp_squeeze_steps += 10
            self._gripper_close_threshold *= 0.8
        if "stabilize_lift" in self._skill_hints:
            # Smaller per-step deltas and lower horizontal coupling reduce
            # oscillation / shear that can break a fragile grasp.
            if self._lift_max_delta is not None:
                self._lift_max_delta *= 0.75
            else:
                self._lift_max_delta = 0.12
            self._kp *= 0.9
            self._lift_horizontal_scale = max(0.0, self._lift_horizontal_scale - 0.2)
        if "efficient_execution" in self._skill_hints:
            self._kp *= 1.5
            self._approach_offset_z *= 0.75
        if "grasp_adjust" in self._skill_hints:
            self._grasp_offset_z = max(0.0, self._grasp_offset_z - 0.015)
            self._grasp_dist_threshold *= 1.5
            self._min_grasp_steps += 3
        if "slower_descent" in self._skill_hints:
            self._kp *= 0.7
            self._approach_offset_z *= 1.2
        if "adaptive_skill" in self._skill_hints:
            self._min_grasp_steps = max(2, self._min_grasp_steps - 2)
            self._lift_height += 0.05
        if "stronger_lift" in self._skill_hints:
            self._kp *= 1.3
            self._lift_height += 0.05
            self._lift_horizontal_scale = min(1.0, self._lift_horizontal_scale + 0.2)
        if "target_tracking" in self._skill_hints:
            self._lift_kp_multiplier = 1.5
            self._lift_horizontal_scale = 1.0
            self._success_threshold = max(0.03, self._success_threshold * 0.8)
        if "faster_approach" in self._skill_hints:
            self._approach_offset_z *= 0.75
            self._kp *= 1.2
        if "larger_servo_gain" in self._skill_hints:
            self._kp *= 1.5

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1
        self._state_step += 1

        if step == 0 and self._skill_hints:
            self._log_hints()

        if self._relative_mode is None:
            self._infer_controller_mode(env)

        eef_pos, eef_quat, object_pos, gripper_pos, target_pos = self._extract_state(observation, env, device)

        if object_pos is None:
            # Fallback open-loop sequence when observation is missing.
            if step < 50:
                action[..., 2] = -0.04
                action = self._set_gripper(action, open=True)
            else:
                action[..., 2] = 0.04
                action = self._set_gripper(action, open=False)
            return action

        if self._state == "APPROACH":
            target = object_pos.clone()
            target[2] += self._approach_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            horiz = torch.norm(object_pos[:2] - eef_pos[:2])
            z_err = abs(eef_pos[2] - target[2])
            if horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5:
                self._transition("DESCEND")

        elif self._state == "DESCEND":
            target = object_pos.clone()
            target[2] += self._grasp_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            if torch.norm(target - eef_pos) < self._grasp_dist_threshold:
                self._transition("GRASP")

        elif self._state == "GRASP":
            action = self._set_gripper(action, open=False)
            # Hold the current pose while closing so absolute-mode controllers do
            # not interpret a zero arm command as a move-to-origin command.
            if not self._relative_mode and eef_pos is not None:
                self._apply_position(action, eef_pos, eef_quat, eef_pos)
            # Transition once the fingers have had time to close.  When the
            # gripper position reading is available we additionally wait until it
            # is below the close threshold, with an optional squeeze extension
            # for objects that need sustained force before lifting.
            squeeze_deadline = self._min_grasp_steps + self._grasp_squeeze_steps
            if self._state_step >= self._min_grasp_steps:
                if gripper_pos is not None and gripper_pos < self._gripper_close_threshold:
                    self._transition("LIFT")
                elif self._state_step >= squeeze_deadline:
                    self._transition("LIFT")

        elif self._state == "LIFT":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=self._lift_horizontal_scale,
                max_delta=self._lift_max_delta,
            )
            action = self._set_gripper(action, open=False)
            # Transition to HOLD when the object is close to the command target
            # (or when the end-effector reaches a pure height target).
            if target_pos is not None and object_pos is not None:
                if torch.norm(target_pos - object_pos) < self._success_threshold:
                    self._transition("HOLD")
            elif eef_pos[2] >= target[2] - 0.03:
                self._transition("HOLD")

        elif self._state == "HOLD":
            action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        # Record a scalar trace step for progress-metric computation.
        if object_pos is not None:
            _append_trace({
                "episode": self._episode_idx,
                "step": step,
                "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
                "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
                "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
                "object_x": float(object_pos[0].item()),
                "object_y": float(object_pos[1].item()),
                "object_z": float(object_pos[2].item()),
                "target_x": float(target_pos[0].item()) if target_pos is not None else None,
                "target_y": float(target_pos[1].item()) if target_pos is not None else None,
                "target_z": float(target_pos[2].item()) if target_pos is not None else None,
                "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
                "action_norm": float(torch.linalg.norm(action).item()),
                "phase": self._state,
            })

        return action

    def _infer_controller_mode(self, env: gym.Env) -> None:
        """Detect whether the arm controller expects relative deltas or absolute poses."""
        action_dim = int(env.action_space.shape[-1]) if hasattr(env.action_space, "shape") else 0
        try:
            cfg = env.unwrapped.cfg
            arm = cfg.actions.arm_action
            self._relative_mode = bool(getattr(arm.controller, "use_relative_mode", True))
            self._action_scale = float(getattr(arm, "scale", 1.0))
            if self._action_scale == 0.0:
                self._action_scale = 1.0
        except Exception:
            # Heuristic fallback: 7-dim action spaces are relative pose (DifferentialIK),
            # 8-dim action spaces are absolute pose (joint pos / RMPflow absolute).
            self._relative_mode = action_dim == 7
            self._action_scale = 1.0
        import sys
        print(
            f"[SERVO_MODE] relative_mode={self._relative_mode} action_scale={self._action_scale} "
            f"action_dim={action_dim}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    def _apply_position(
        self,
        action: torch.Tensor,
        eef_pos: torch.Tensor | None,
        eef_quat: torch.Tensor | None,
        target: torch.Tensor,
        kp_multiplier: float = 1.0,
        horizontal_scale: float = 1.0,
        max_delta: float | None = None,
    ) -> None:
        """Write a position (and orientation) command into ``action[..., :3]``."""
        if eef_pos is None:
            return
        delta = self._kp * kp_multiplier * (target - eef_pos)
        if horizontal_scale != 1.0:
            delta[:2] *= horizontal_scale
        # In relative mode we want to saturate the action to maximize step size
        # (the controller is heavily damped). In absolute mode keep steps small
        # so mock/unit-test environments remain stable.
        if max_delta is None:
            max_delta = 0.5 if self._relative_mode else 0.1
        delta = torch.clamp(delta, -max_delta, max_delta)

        if self._relative_mode:
            # Relative-mode action is a delta pose in the end-effector body frame,
            # scaled by action_scale. The arm command has 6 dims:
            #   [dx, dy, dz, droll, dpitch, dyaw]
            # followed by the gripper dim.
            body_delta = delta.clone()
            # Live runs with the Arena DifferentialIK relative-pose controller show
            # that world-frame deltas map directly to the action axes (no sign
            # flips) when the controller is configured in relative mode.
            cmd = body_delta / self._action_scale
            action[..., :3] = torch.clamp(cmd, -1.0, 1.0)
            if action.shape[-1] >= 6:
                action[..., 3:6] = 0.0
        else:
            # Absolute-mode action is the desired body pose in world frame.
            action[..., :3] = eef_pos + delta
            if action.shape[-1] >= 7:
                quat = (
                    eef_quat
                    if eef_quat is not None and eef_quat.numel() >= 4
                    else torch.tensor([0.0, 0.0, 0.0, 1.0], device=action.device, dtype=action.dtype)
                )
                action[..., 3:7] = quat[:4]

    def _set_gripper(self, action: torch.Tensor, open: bool) -> torch.Tensor:
        """Set the gripper command dimension.

        In relative pose mode the gripper is the 7th dim (after the 6-dim arm
        delta pose). In absolute pose mode it is the last of 8 dims.
        """
        value = 1.0 if open else -1.0
        if self._relative_mode and action.shape[-1] >= 7:
            action[..., 6] = value
        elif action.shape[-1] >= 8:
            action[..., -1] = value
        return action

    def _extract_state(
        self, observation: GymSpacesDict, env: gym.Env, device: torch.device
    ) -> tuple[
        torch.Tensor | None,
        torch.Tensor | None,
        torch.Tensor | None,
        torch.Tensor | None,
        torch.Tensor | None,
    ]:
        """Extract world-frame eef_pos, eef_quat, object_pos, gripper_pos, and target_pos."""
        # Prefer scene data because it is always in the world frame. The policy
        # observation terms may return object positions in the robot root frame,
        # which would break the servo error if used directly.
        eef_pos, eef_quat, object_pos, gripper_pos = self._extract_from_scene(env, device)

        # Fallback to observation terms if scene extraction fails.
        if eef_pos is None or object_pos is None or gripper_pos is None:
            eef_pos_o, object_pos_o, gripper_pos_o = self._extract_obs(observation, device)
            if eef_pos is None:
                eef_pos = eef_pos_o
            if object_pos is None:
                object_pos = object_pos_o
            if gripper_pos is None:
                gripper_pos = gripper_pos_o

        target_pos = self._extract_target_world(observation, env, device)
        return eef_pos, eef_quat, object_pos, gripper_pos, target_pos

    def _extract_target_world(
        self, observation: GymSpacesDict, env: gym.Env, device: torch.device
    ) -> torch.Tensor | None:
        """Read the command target position and transform it to the world frame.

        The command manager stores targets in the robot root frame; Arena's
        success criterion compares object world position to the world-frame goal.
        Different tasks name the command term differently, so we try a list of
        common names and fall back to the raw task observation buffer.
        """
        root_pos, root_quat = None, None
        for cmd_name in ("object_pose", "pose_command", "target_pose"):
            try:
                cm = env.unwrapped.command_manager
                cmd = cm.get_command(cmd_name)
                t = torch.as_tensor(cmd, device=device).squeeze()
                if t.numel() < 3:
                    continue
                des_pos_b = t[:3]
                if root_pos is None:
                    root_pos, root_quat = self._extract_robot_root(env, device)
                if root_pos is not None and root_quat is not None:
                    from isaaclab.utils.math import combine_frame_transforms
                    target_w, _ = combine_frame_transforms(
                        root_pos.unsqueeze(0),
                        root_quat.unsqueeze(0),
                        des_pos_b.unsqueeze(0),
                    )
                    return target_w.squeeze()
            except Exception:
                continue

        # Fallback: read task_obs from the env's internal observation buffer.
        try:
            obs_buf = getattr(env, "_obs_buf", None) or getattr(env.unwrapped, "_obs_buf", None)
            if isinstance(obs_buf, dict) and "task_obs" in obs_buf:
                task_obs = obs_buf["task_obs"]
            elif isinstance(observation, dict):
                task_obs = observation.get("task_obs")
            else:
                task_obs = None
            if task_obs is not None:
                if hasattr(task_obs, "squeeze"):
                    task_obs = task_obs.squeeze()
                t = self._to_tensor(task_obs, device)
                if t is not None and t.numel() >= 3:
                    return t[:3].squeeze()
        except Exception:
            pass

        return None

    def _extract_robot_root(
        self, env: gym.Env, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None]:
        """Return the robot root position/quaternion in world frame."""
        try:
            scene = getattr(env.unwrapped, "scene", None)
            if scene is None:
                return None, None
            robot = scene["robot"]
            data = robot.data
            pos = data.root_pos_w.squeeze().to(device)
            quat = data.root_quat_w.squeeze().to(device)
            if pos.ndim > 1:
                pos = pos[0]
            if quat.ndim > 1:
                quat = quat[0]
            return pos, quat
        except Exception:
            return None, None

    def _extract_obs(
        self, observation: GymSpacesDict, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None]:
        pol = observation
        if isinstance(observation, dict):
            pol = observation.get("policy", observation)
        if not isinstance(pol, dict):
            return None, None, None

        eef_pos = self._to_tensor(pol.get("eef_pos"), device)
        object_pos = self._to_tensor(pol.get("object_pos"), device)
        gripper_pos = self._to_tensor(pol.get("gripper_pos"), device)
        if gripper_pos is not None and gripper_pos.numel() == 0:
            gripper_pos = None
        return eef_pos, object_pos, gripper_pos

    def _extract_from_scene(
        self, env: gym.Env, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None, torch.Tensor | None]:
        """Read eef/object/gripper data from the IsaacLab scene (world frame)."""
        try:
            scene = getattr(env.unwrapped, "scene", None)
            if scene is None:
                return None, None, None, None

            scene_keys = list(scene.keys())
            object_candidates = {"dex_cube", "object", "cube", "mug", "cracker_box", "mustard_bottle"}
            object_pos = None
            for key in scene_keys:
                if key in object_candidates:
                    obj = scene[key]
                    data = getattr(obj, "data", None)
                    if data is not None and hasattr(data, "root_pos_w"):
                        object_pos = data.root_pos_w.squeeze().to(device)
                        break

            eef_pos = None
            eef_quat = None
            if "ee_frame" in scene_keys:
                ee_frame = scene["ee_frame"]
                data = getattr(ee_frame, "data", None)
                if data is not None:
                    # Prefer the controller target frame because the DifferentialIK
                    # relative controller drives this frame; the actual sensor
                    # source lags and using it for servo feedback under-damps the arm.
                    for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                        if hasattr(data, attr):
                            pos = getattr(data, attr).squeeze().to(device)
                            if pos.ndim > 1:
                                pos = pos[0]
                            if pos.numel() == 3:
                                eef_pos = pos
                                break
                    for attr in ("quat_w", "target_quat_w", "source_quat_w"):
                        if hasattr(data, attr):
                            quat = getattr(data, attr).squeeze().to(device)
                            if quat.ndim > 1:
                                quat = quat[0]
                            if quat.numel() >= 4:
                                eef_quat = quat
                                break

            gripper_pos = None
            if "robot" in scene_keys:
                robot = scene["robot"]
                data = getattr(robot, "data", None)
                if data is not None and hasattr(data, "joint_pos"):
                    joints = data.joint_pos.squeeze()
                    if joints.numel() >= 2:
                        gripper_pos = joints[-2:].mean().to(device)

            return eef_pos, eef_quat, object_pos, gripper_pos
        except Exception as e:
            import sys
            print(f"[SERVO_DEBUG] scene extraction error: {e}", file=sys.stderr)
            sys.stderr.flush()
            return None, None, None, None

    @staticmethod
    def _to_tensor(value: Any, device: torch.device) -> torch.Tensor | None:
        if value is None:
            return None
        if isinstance(value, torch.Tensor):
            return value.squeeze().to(device)
        import numpy as np

        arr = np.asarray(value).squeeze()
        return torch.from_numpy(arr).to(device).float()

    @staticmethod
    def _fmt(tensor: torch.Tensor | None) -> str:
        if tensor is None:
            return "None"
        return str(tensor.detach().cpu().tolist())

    def _transition(self, new_state: str) -> None:
        self._state = new_state
        self._state_step = 0

    def _log_hints(self) -> None:
        import sys
        print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
        print(
            f"[HEURISTIC_SKILL_HINTS] params: approach_z={self._approach_offset_z:.4f} "
            f"grasp_z={self._grasp_offset_z:.4f} lift_h={self._lift_height:.4f} "
            f"kp={self._kp:.4f} grasp_dist={self._grasp_dist_threshold:.4f} "
            f"gripper_close={self._gripper_close_threshold:.4f} min_grasp={self._min_grasp_steps}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._state = "APPROACH"
        self._state_step = 0
        self._episode_idx += 1
        self._last_gate_diagnostics = None

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoLiftPolicy":
        return HeuristicServoLiftPolicy(HeuristicServoLiftPolicyArgs.from_cli_args(args))


class HeuristicServoGoalPosePolicy(HeuristicServoLiftPolicy):
    """Closed-loop servo heuristic for goal-pose / reorientation tasks.

    Reuses the lift state machine through ``GRASP`` and ``LIFT``, then aligns
    the grasped object with the command target pose, releases the gripper, and
    holds. Works with the absolute-pose Franka IK controller configured by
    ``ArenaAdapter``.
    """

    name = "heuristic_servo_goal_pose"
    config_class = HeuristicServoGoalPosePolicyArgs

    def __init__(self, config: HeuristicServoGoalPosePolicyArgs):
        super().__init__(config)
        # Record schema version so downstream analysis can distinguish
        # object-yaw error from end-effector-yaw error.
        _write_trace_metadata({
            "trace_schema_version": "goal_pose_trace_v2",
            "orientation_error_definition": "object_yaw_error_to_target_yaw",
            "eef_yaw_recorded": True,
        })
        self._min_release_steps = config.min_release_steps
        self._align_height_offset = config.align_height_offset
        self._orientation_threshold = config.orientation_threshold
        self._grasp_z_tolerance = getattr(config, "grasp_z_tolerance", 0.02)
        self._fixed_target_pos = config.fixed_target_pos
        self._fixed_target_quat = config.fixed_target_quat
        self._release_at_target = config.release_at_target
        self._require_orientation_alignment = config.require_orientation_alignment
        self._align_horizontal_scale = config.align_horizontal_scale
        self._align_kp_multiplier = config.align_kp_multiplier
        self._lift_max_delta = config.lift_max_delta
        self._align_max_delta = config.align_max_delta

        # Grasp-stability v2 controls.
        self._pre_grasp_orient = config.pre_grasp_orient
        self._grasp_target_yaw_offset = config.grasp_target_yaw_offset
        self._pre_grasp_yaw_threshold = config.pre_grasp_yaw_threshold
        self._reorient_before_align = config.reorient_before_align
        self._reorient_height_offset = config.reorient_height_offset
        self._max_lift_delta_z = config.max_lift_delta_z
        self._align_yaw_during_approach = getattr(
            config, "align_yaw_during_approach", False
        )
        self._approach_yaw_offset = getattr(
            config, "approach_yaw_offset", math.pi
        )

        # Reachability-aware approach planner (Sprint 1 v1.6).
        self._reachability_strategy = getattr(config, "reachability_strategy", "direct_descend")
        self._high_pregrasp_z_offset = getattr(config, "high_pregrasp_z_offset", 0.25)
        self._side_pregrasp_y_offset = getattr(config, "side_pregrasp_y_offset", -0.05)
        self._side_pregrasp_z_offset = getattr(config, "side_pregrasp_z_offset", 0.15)
        self._reachability_estimator: Any = None
        if self._reachability_strategy != "direct_descend" and ReachabilityRiskEstimator is not None:
            self._reachability_estimator = ReachabilityRiskEstimator(
                positive_y_threshold=getattr(config, "reachability_positive_y_threshold", 0.01),
                positive_yaw_threshold=getattr(config, "reachability_positive_yaw_threshold", 0.0),
            )
        self._reachability_risk: Any = None

        # Pre-grasp yaw alignment v2 (Sprint 2 v1.6).
        self._pre_grasp_yaw_align_v2 = getattr(config, "pre_grasp_yaw_align_v2", False)
        self._pre_grasp_yaw_fraction = getattr(config, "pre_grasp_yaw_fraction", 0.8)
        self._pre_grasp_yaw_max_step = getattr(config, "pre_grasp_yaw_max_step", 0.2)
        self._pre_grasp_yaw_settle_steps = getattr(config, "pre_grasp_yaw_settle_steps", 3)
        self._post_grasp_yaw_residual_fraction = getattr(config, "post_grasp_yaw_residual_fraction", 0.2)
        self._pre_grasp_yaw_safety_distance = getattr(config, "pre_grasp_yaw_safety_distance", 0.04)

        # v3 intervention controls.
        self._verify_object_following_steps = config.verify_object_following_steps
        self._object_following_distance_threshold = config.object_following_distance_threshold
        self._use_quaternion_orientation_target = config.use_quaternion_orientation_target
        self._yaw_step_size = config.yaw_step_size
        self._stabilize_steps_after_yaw = config.stabilize_steps_after_yaw
        self._skip_broken_yaw_control = config.skip_broken_yaw_control
        self._target_yaw_override = getattr(config, "target_yaw_override", None)

        # Large-yaw targeted intervention strategy mapping (Sprint 5 v1.7).
        # We deliberately keep this as a thin re-parameterisation of existing
        # phases so we can ablate strategies without rewriting the state machine.
        self._large_yaw_strategy = getattr(config, "large_yaw_strategy", None)
        self._disable_inhand_reorient = getattr(config, "disable_inhand_reorient", False)
        self._lift_height_before_yaw = getattr(config, "lift_height_before_yaw", 0.05)
        if self._large_yaw_strategy == "grasp_at_target_yaw":
            self._pre_grasp_yaw_align_v2 = True
            self._pre_grasp_yaw_fraction = 1.0
            self._post_grasp_yaw_residual_fraction = 0.0
            self._reorient_before_align = False
        elif self._large_yaw_strategy == "low_height_incremental_yaw":
            self._pre_grasp_yaw_align_v2 = True
            self._pre_grasp_yaw_fraction = getattr(config, "pre_grasp_yaw_fraction", 0.8)
            self._post_grasp_yaw_residual_fraction = getattr(config, "post_grasp_yaw_residual_fraction", 0.2)
            self._lift_height = self._lift_height_before_yaw
            self._reorient_height_offset = self._lift_height_before_yaw
            self._reorient_before_align = True
        if self._disable_inhand_reorient:
            self._reorient_before_align = False

        # Object-following verification state.
        self._object_following_verified = False
        self._lift_start_object_pos: torch.Tensor | None = None
        self._lift_start_eef_pos: torch.Tensor | None = None
        self._initial_object_pos: torch.Tensor | None = None
        self._last_gate_diagnostics: dict[str, Any] | None = None
        self._seed_randomization_done = False

        # Structural FailureToHint v3.1 regrasp / contact-diagnosis state.
        self._enable_regrasp = getattr(config, "enable_regrasp", False)
        self._max_regrasp_attempts = getattr(config, "max_regrasp_attempts", 0)
        self._regrasp_xy_offsets = getattr(config, "regrasp_xy_offsets", None) or []
        self._verify_lift_response_steps = getattr(config, "verify_lift_response_steps", 0)
        self._min_lift_response_z = getattr(config, "min_lift_response_z", 0.01)
        self._regrasp_attempt_count = 0
        self._grasp_start_object_pos: torch.Tensor | None = None
        self._grasp_start_eef_pos: torch.Tensor | None = None
        self._lift_verify_start_object_z: float | None = None
        self._contact_proxy = "unknown"
        self._grasp_effective = False
        self._lift_response_z = 0.0

        # Object-geometry adaptation state (Sprint 4).
        self._use_object_geometry_adaptation = config.use_object_geometry_adaptation
        self._object_geometry_adapter: Any = None
        self._object_geometry: Any = None
        if ObjectGeometryAdapter is not None and self._use_object_geometry_adaptation:
            self._object_geometry_adapter = ObjectGeometryAdapter()
            if config.object_geometry is not None:
                self._object_geometry = extract_geometry_from_config(config.object_geometry)
                self._apply_geometry_adaptation(self._object_geometry)

        # Goal-pose specific hint effects.
        if "precision_placement" in self._skill_hints:
            self._success_threshold = max(0.03, self._success_threshold * 0.8)
            self._kp *= 0.9
        if "release_at_target" in self._skill_hints:
            self._release_at_target = True
            self._min_release_steps += 5
        if "orient_adjust" in self._skill_hints or "orientation_aware_grasp" in self._skill_hints:
            self._require_orientation_alignment = True
            self._orientation_threshold *= 0.8
            self._pre_grasp_orient = True
            self._pre_grasp_yaw_threshold *= 0.7
        if "two_stage_reorientation" in self._skill_hints:
            self._require_orientation_alignment = True
            self._orientation_threshold *= 0.7
            self._reorient_before_align = True
            self._reorient_height_offset = max(0.03, self._reorient_height_offset - 0.02)
        if "stabilize_lift" in self._skill_hints or "reduce_xy_motion" in self._skill_hints:
            if self._align_max_delta is not None:
                self._align_max_delta *= 0.75
            else:
                self._align_max_delta = 0.06
            self._lift_horizontal_scale = max(0.0, self._lift_horizontal_scale - 0.2)
            self._lift_kp_multiplier *= 0.9
        if "longer_squeeze" in self._skill_hints or "longer_gripper_close" in self._skill_hints:
            self._min_grasp_steps += 5
            self._grasp_squeeze_steps += 10
            self._gripper_close_threshold *= 0.8
        if "maintain_grip_force" in self._skill_hints:
            self._min_grasp_steps += 3
            self._grasp_squeeze_steps += 5
        if "lower_lift_acceleration" in self._skill_hints or "gentle_lift" in self._skill_hints:
            self._max_lift_delta_z *= 0.7
            self._lift_kp_multiplier *= 0.8
        if "centered_grasp" in self._skill_hints:
            self._grasp_target_yaw_offset = math.pi / 2.0
            self._pre_grasp_orient = True

        # v3 recipe hint effects.
        if "incremental_yaw_reorientation" in self._skill_hints:
            self._yaw_step_size = max(0.05, self._yaw_step_size * 0.5)
            self._stabilize_steps_after_yaw = max(5, self._stabilize_steps_after_yaw)
        if "stabilize_after_rotation" in self._skill_hints:
            self._stabilize_steps_after_yaw = max(10, self._stabilize_steps_after_yaw)
        if "reduce_rotation_acceleration" in self._skill_hints:
            self._max_lift_delta_z *= 0.7
        if "use_object_following_grasp_metric" in self._skill_hints:
            # The policy already uses object-following verification when enabled.
            self._verify_object_following_steps = max(3, self._verify_object_following_steps)
        if "verify_object_following" in self._skill_hints:
            self._verify_object_following_steps = max(5, self._verify_object_following_steps)
        if "use_effective_yaw_axis" in self._skill_hints:
            # Rotational calibration showed relative yaw is broken; rely on
            # quaternion target mode if the action space supports it.
            self._use_quaternion_orientation_target = True
        if "skip_broken_yaw" in self._skill_hints:
            self._skip_broken_yaw_control = True
            self._reorient_before_align = False
            # Do not force pre_grasp_orient here; if the user wants a settling
            # pause they can set it explicitly in the config.  Forcing it on
            # makes the policy hover while the object falls out of reach.

        # If we explicitly skip broken yaw, make sure we do not try to use it.
        if self._skip_broken_yaw_control:
            self._reorient_before_align = False
            self._require_orientation_alignment = False

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1
        self._state_step += 1

        if step == 0 and self._skill_hints:
            self._log_hints()

        # Apply host-forwarded seed-driven object pose randomization on the first
        # policy step.  Arena's object placer does not always honor the seed, so
        # this ensures different seeds produce visibly different initial poses.
        if step == 0 and not self._seed_randomization_done:
            self._seed_randomization_done = True
            raw_seed = os.environ.get("ROSCLAW_ARENA_SEED")
            if raw_seed is not None:
                try:
                    _randomize_object_pose_from_seed(env, int(raw_seed))
                except Exception as exc:
                    print(
                        f"[POLICY_SEED_RANDOMIZATION] top-level call failed: {exc}",
                        file=sys.stderr,
                    )
                    sys.stderr.flush()

        if self._relative_mode is None:
            self._infer_controller_mode(env)

        # Lazy geometry extraction: the policy config may contain a declared
        # geometry, otherwise inspect the scene on the first step.
        if (
            self._use_object_geometry_adaptation
            and self._object_geometry is None
            and extract_geometry_from_scene is not None
            and step == 0
        ):
            try:
                geom = extract_geometry_from_scene(getattr(env, "unwrapped", env).scene, object_name="unknown")
                self._object_geometry = geom
                self._apply_geometry_adaptation(geom)
            except Exception as e:
                import sys

                print(f"[OBJECT_GEOMETRY] scene extraction failed: {e}", file=sys.stderr)
                sys.stderr.flush()

        eef_pos, eef_quat, object_pos, gripper_pos, target_pos = self._extract_state(observation, env, device)
        target_quat = self._extract_target_quat_world(observation, env, device)
        if target_pos is None and self._fixed_target_pos is not None and object_pos is not None:
            target_pos = torch.as_tensor(self._fixed_target_pos, device=device, dtype=object_pos.dtype)
        if target_quat is None and self._fixed_target_quat is not None:
            dtype = eef_quat.dtype if eef_quat is not None else torch.float32
            target_quat = torch.as_tensor(self._fixed_target_quat, device=device, dtype=dtype)

        # Optional cross-orientation diagnostic: override the environment's
        # target yaw with a fixed world-frame yaw.  This only affects the
        # policy's desired orientation; the Arena success criterion may still
        # use the original pi/2 target, so success_rate should be interpreted
        # together with the trace's object_yaw_error.
        if self._target_yaw_override is not None:
            yaw = float(self._target_yaw_override)
            target_quat = torch.tensor(
                [0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)],
                device=device,
                dtype=(target_quat.dtype if target_quat is not None else torch.float32),
            )
            if step == 0:
                import sys

                sys.stderr.write(
                    f"[GOAL_POSE] target_yaw_override active: {yaw:.4f} rad "
                    f"(quat=[{target_quat[0]:.4f}, {target_quat[1]:.4f}, {target_quat[2]:.4f}, {target_quat[3]:.4f}])\n"
                )
                sys.stderr.flush()

        # Absolute-pose controllers expect commands in the robot base frame.
        # Convert world-frame poses so the rest of the state machine can treat
        # eef_pos/eef_quat and all targets as base-frame quantities.
        if not self._relative_mode and eef_pos is not None:
            eef_pos_b, eef_quat_b = self._get_eef_pose_base(env, device)
            if eef_pos_b is not None:
                identity_quat = torch.tensor([0.0, 0.0, 0.0, 1.0], device=device)
                if object_pos is not None:
                    object_pos, _ = self._world_pose_to_base(object_pos, identity_quat, env, device)
                if target_pos is not None:
                    target_pos, _ = self._world_pose_to_base(target_pos, identity_quat, env, device)
                if target_quat is not None:
                    _, target_quat = self._world_pose_to_base(
                        torch.zeros(3, device=device), target_quat, env, device
                    )
                eef_pos = eef_pos_b
                eef_quat = eef_quat_b

        # Remember the object's base-frame position at the first observation so
        # the rest of the state machine has a stable placement target when the
        # task does not provide an explicit command target.
        if object_pos is not None and self._initial_object_pos is None:
            self._initial_object_pos = object_pos.clone()

        # Fall back to the object's initial pose as the placement target.  This
        # keeps LIFT / REORIENT / ALIGN from chasing the moving object.
        if target_pos is None and self._initial_object_pos is not None:
            target_pos = self._initial_object_pos.clone()

        if object_pos is None:
            # Fallback open-loop sequence when observations are missing.
            if step < 50:
                action[..., 2] = -0.04
                action = self._set_gripper(action, open=True)
            else:
                action[..., 2] = 0.04
                action = self._set_gripper(action, open=False)
            return action

        if self._state == "APPROACH":
            # Evaluate reachability risk once at the start of approach so the
            # gripper can take an alternative path *before* colliding with the
            # object.  Waiting until the gripper is close to the object is too
            # late for the positive-y / positive-yaw corner-collision seeds.
            if (
                self._reachability_strategy != "direct_descend"
                and self._reachability_estimator is not None
                and self._reachability_risk is None
            ):
                object_pos_tuple = tuple(float(v.item()) for v in object_pos[:3])
                object_yaw = self._extract_object_yaw(env, device)
                self._reachability_risk = self._reachability_estimator.estimate(
                    object_pos_tuple, object_yaw=object_yaw
                )

            # Default target is directly above the object.
            target = object_pos.clone()
            target[2] += self._approach_offset_z
            next_phase: str | None = None

            if (
                self._reachability_strategy != "direct_descend"
                and self._reachability_risk is not None
            ):
                if self._reachability_risk.risk_level == "high":
                    if self._reachability_strategy in (
                        "side_pregrasp_positive_y",
                        "side_pregrasp",
                    ):
                        next_phase = "SIDE_PREGRASP"
                    else:
                        # two_stage / high_pregrasp default
                        next_phase = "HIGH_PREGRASP"
                # NOTE: medium risk is intentionally ignored for the
                # side_pregrasp_positive_y strategy.  The 50-seed regression showed
                # that raising to a high pregrasp for positive-y / negative-yaw
                # seeds (the only medium-risk case seen on dex_cube) caused
                # approach collisions on seeds that succeeded with direct_descend.

                # Set the approach waypoint accordingly.
                if next_phase == "HIGH_PREGRASP":
                    target[2] = object_pos[2] + self._high_pregrasp_z_offset
                elif next_phase == "SIDE_PREGRASP":
                    target[1] += self._side_pregrasp_y_offset
                    target[2] = object_pos[2] + self._side_pregrasp_z_offset

            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)

            # Optionally rotate the gripper toward the object's yaw while we are
            # still above it.  This can avoid kinematic dead-ends where the
            # default gripper attitude cannot reach the object.  The target yaw is
            # computed in the world frame and then converted to the robot base
            # frame so the absolute-mode controller receives a consistent
            # base-frame quaternion.
            if self._align_yaw_during_approach and eef_quat is not None:
                object_yaw = self._extract_object_yaw(env, device)
                if object_yaw is not None:
                    desired_yaw = float(object_yaw) + float(self._approach_yaw_offset)
                    target_quat_pre_w = torch.tensor(
                        [0.0, 0.0, math.sin(desired_yaw / 2.0), math.cos(desired_yaw / 2.0)],
                        device=device,
                        dtype=eef_quat.dtype,
                    )
                    _, target_quat_pre_b = self._world_pose_to_base(
                        torch.zeros(3, device=device, dtype=eef_quat.dtype),
                        target_quat_pre_w,
                        env,
                        device,
                    )
                    self._apply_orientation(action, eef_quat, target_quat_pre_b)

            # Transition once the gripper reaches the current waypoint.
            horiz = torch.norm(target[:2] - eef_pos[:2])
            z_err = abs(eef_pos[2] - target[2])
            if horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5:
                if next_phase is not None:
                    self._transition(next_phase)
                elif self._pre_grasp_yaw_align_v2:
                    self._transition("PRE_GRASP_YAW_ALIGN")
                elif self._pre_grasp_orient:
                    self._transition("PRE_GRASP_ORIENT")
                else:
                    self._transition("DESCEND")

        elif self._state == "PRE_GRASP_YAW_ALIGN":
            # Align gripper yaw before descending, while still above the object.
            target = object_pos.clone()
            target[2] += self._approach_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            object_yaw = self._extract_object_yaw(env, device)
            if (
                object_yaw is not None
                and eef_quat is not None
                and not self._skip_broken_yaw_control
            ):
                desired_yaw = object_yaw + self._grasp_target_yaw_offset
                desired_yaw_quat = torch.tensor(
                    [0.0, 0.0, math.sin(desired_yaw / 2.0), math.cos(desired_yaw / 2.0)],
                    device=device,
                    dtype=eef_quat.dtype,
                )
                self._apply_orientation(action, eef_quat, desired_yaw_quat)
            # Abort yaw alignment if we are already too close to the object.
            safety_ok = torch.norm(object_pos[:2] - eef_pos[:2]) > self._pre_grasp_yaw_safety_distance
            yaw_err = 0.0
            if object_yaw is not None and eef_quat is not None and not self._skip_broken_yaw_control:
                desired_yaw = object_yaw + self._grasp_target_yaw_offset
                current_yaw = self._quat_to_yaw(eef_quat)
                yaw_err = abs(self._angle_diff(desired_yaw, current_yaw))
            yaw_ok = object_yaw is None or yaw_err < self._pre_grasp_yaw_threshold or self._skip_broken_yaw_control
            position_ok = torch.norm(object_pos[:2] - eef_pos[:2]) < self._approach_horizontal_threshold
            if position_ok and (yaw_ok or not safety_ok or self._state_step >= 30):
                if self._pre_grasp_orient:
                    self._transition("PRE_GRASP_ORIENT")
                else:
                    self._transition("DESCEND")

        elif self._state == "HIGH_PREGRASP":
            # Intermediate high waypoint to avoid workspace collision.
            target = object_pos.clone()
            target[2] += self._high_pregrasp_z_offset
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            z_err = abs(eef_pos[2] - target[2])
            if z_err < self._approach_offset_z * 0.5:
                use_side = (
                    self._reachability_strategy in ("side_pregrasp_positive_y", "side_pregrasp", "two_stage")
                    or (
                        self._reachability_risk is not None
                        and self._reachability_risk.recommended_approach == "side_pregrasp_positive_y"
                        and self._reachability_strategy != "high_pregrasp"
                    )
                )
                if use_side:
                    self._transition("SIDE_PREGRASP")
                elif self._pre_grasp_orient:
                    self._transition("PRE_GRASP_ORIENT")
                else:
                    self._transition("DESCEND")

        elif self._state == "SIDE_PREGRASP":
            # Approach from the negative-y side for positive-y workspace edge.
            target = object_pos.clone()
            target[1] += self._side_pregrasp_y_offset
            target[2] += self._side_pregrasp_z_offset
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            horiz = torch.norm(object_pos[:2] - eef_pos[:2])
            z_err = abs(eef_pos[2] - target[2])
            if horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5:
                if self._pre_grasp_orient:
                    self._transition("PRE_GRASP_ORIENT")
                else:
                    self._transition("DESCEND")

        elif self._state == "PRE_GRASP_ORIENT":
            # Stay above the object.  When yaw control is broken this phase acts as
            # a short settling pause instead of an active reorientation.
            target = object_pos.clone()
            target[2] += self._approach_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            object_yaw = self._extract_object_yaw(env, device)
            if object_yaw is not None and eef_quat is not None and not self._skip_broken_yaw_control:
                desired_yaw = object_yaw + self._grasp_target_yaw_offset
                target_quat_pre = torch.tensor(
                    [0.0, 0.0, math.sin(desired_yaw / 2.0), math.cos(desired_yaw / 2.0)],
                    device=device,
                    dtype=eef_quat.dtype,
                )
                self._apply_orientation(action, eef_quat, target_quat_pre)
            horiz = torch.norm(object_pos[:2] - eef_pos[:2])
            z_err = abs(eef_pos[2] - target[2])
            yaw_err = 0.0
            if object_yaw is not None and eef_quat is not None and not self._skip_broken_yaw_control:
                desired_yaw = object_yaw + self._grasp_target_yaw_offset
                current_yaw = self._quat_to_yaw(eef_quat)
                yaw_err = abs(self._angle_diff(desired_yaw, current_yaw))
            yaw_ok = object_yaw is None or yaw_err < self._pre_grasp_yaw_threshold or self._skip_broken_yaw_control
            position_ok = horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5
            # When yaw is broken, use a short pause (5 steps) to stabilise above
            # the object before descending.
            settle_ok = self._skip_broken_yaw_control and self._state_step >= 5
            if position_ok and (yaw_ok or self._state_step >= 30 or settle_ok):
                self._transition("DESCEND")

        elif self._state == "DESCEND":
            target = object_pos.clone()
            target[2] += self._grasp_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            dist_error = torch.norm(target - eef_pos)
            z_error = abs(eef_pos[2].item() - target[2].item())
            dist_ok = dist_error < self._grasp_dist_threshold
            z_ok = z_error < self._grasp_z_tolerance
            self._last_gate_diagnostics = {
                "gate_phase": "DESCEND",
                "grasp_target_x": float(target[0].item()),
                "grasp_target_y": float(target[1].item()),
                "grasp_target_z": float(target[2].item()),
                "grasp_dist_error": float(dist_error.item()),
                "grasp_z_error": float(z_error),
                "grasp_dist_threshold": float(self._grasp_dist_threshold),
                "grasp_z_tolerance": float(self._grasp_z_tolerance),
                "condition_dist_ok": bool(dist_ok),
                "condition_z_ok": bool(z_ok),
                "transition_allowed": bool(dist_ok and z_ok),
                "transition_blocking_reason": (
                    None if (dist_ok and z_ok) else
                    "z_not_ok" if not z_ok else
                    "dist_not_ok" if not dist_ok else
                    "unknown"
                ),
            }
            if dist_ok and z_ok:
                self._transition("GRASP")

        elif self._state == "GRASP":
            action = self._set_gripper(action, open=False)
            # Record the object/eef pose at the start of the close phase so that
            # CONTACT_VERIFY can diagnose whether the gripper actually engaged
            # the object or pushed it away.
            if self._state_step == 0:
                if object_pos is not None:
                    self._grasp_start_object_pos = object_pos.clone()
                if eef_pos is not None:
                    self._grasp_start_eef_pos = eef_pos.clone()
            # In absolute pose mode a zero arm command means "move to the origin",
            # so hold the current end-effector pose while the fingers close.  This
            # prevents the gripper from drifting down/away during the close phase
            # and missing the object.
            if not self._relative_mode and eef_pos is not None:
                self._apply_position(action, eef_pos, eef_quat, eef_pos)
            squeeze_deadline = self._min_grasp_steps + self._grasp_squeeze_steps
            if self._state_step >= self._min_grasp_steps:
                close_ok = gripper_pos is not None and gripper_pos < self._gripper_close_threshold
                if close_ok or self._state_step >= squeeze_deadline:
                    if self._enable_regrasp and self._verify_lift_response_steps > 0:
                        self._transition("CONTACT_VERIFY")
                    else:
                        self._transition("LIFT")

        elif self._state == "CONTACT_VERIFY":
            # Hold the current pose with the gripper closed and classify the
            # contact quality before committing to a lift.  This is the first
            # structural diagnosis gate used by FailureToHint v3.1.
            if not self._relative_mode and eef_pos is not None:
                self._apply_position(action, eef_pos, eef_quat, eef_pos)
            action = self._set_gripper(action, open=False)
            self._contact_proxy = self._classify_contact_proxy(gripper_pos, object_pos, eef_pos)
            self._grasp_effective = self._contact_proxy in ("likely_contact", "weak_contact_no_lift")
            if self._state_step >= 3:
                if self._enable_regrasp and self._verify_lift_response_steps > 0:
                    self._transition("LIFT_VERIFY")
                else:
                    self._transition("LIFT")

        elif self._state == "LIFT_VERIFY":
            # Perform a short guarded lift and measure the object's response.
            # If the object does not move up with the gripper, attempt regrasp.
            target = object_pos.clone() if object_pos is not None else (eef_pos.clone() if eef_pos is not None else torch.zeros(3, device=device))
            target[2] += 0.06
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=0.0,
                max_delta=self._max_lift_delta_z,
            )
            action = self._set_gripper(action, open=False)
            if self._lift_verify_start_object_z is None and object_pos is not None:
                self._lift_verify_start_object_z = float(object_pos[2].item())
            if self._state_step >= self._verify_lift_response_steps:
                if object_pos is not None and self._lift_verify_start_object_z is not None:
                    self._lift_response_z = float(object_pos[2].item()) - self._lift_verify_start_object_z
                else:
                    self._lift_response_z = 0.0
                if self._lift_response_z >= self._min_lift_response_z:
                    if self._verify_object_following_steps > 0 and not self._object_following_verified:
                        self._lift_start_object_pos = object_pos.clone() if object_pos is not None else None
                        self._lift_start_eef_pos = eef_pos.clone() if eef_pos is not None else None
                        self._transition("VERIFY_OBJECT_FOLLOWING")
                    else:
                        self._transition("LIFT")
                elif self._regrasp_attempt_count < self._max_regrasp_attempts:
                    self._transition("REGRASP")
                else:
                    self._transition("HOLD")

        elif self._state == "REGRASP":
            # Open the gripper, retreat to a safe approach height, shift the
            # grasp target horizontally, and try DESCEND again.
            target = object_pos.clone() if object_pos is not None else (eef_pos.clone() if eef_pos is not None else torch.zeros(3, device=device))
            target[2] += self._approach_offset_z
            if self._regrasp_attempt_count < len(self._regrasp_xy_offsets):
                offset = self._regrasp_xy_offsets[self._regrasp_attempt_count]
                target[0] += float(offset[0])
                target[1] += float(offset[1])
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            horiz = torch.norm(target[:2] - eef_pos[:2]) if eef_pos is not None else torch.tensor(0.0, device=device)
            z_err = abs((eef_pos[2] if eef_pos is not None else target[2]) - target[2])
            if horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5:
                self._regrasp_attempt_count += 1
                self._contact_proxy = "unknown"
                self._grasp_effective = False
                self._lift_response_z = 0.0
                self._lift_verify_start_object_z = None
                if self._pre_grasp_yaw_align_v2:
                    self._transition("PRE_GRASP_YAW_ALIGN")
                else:
                    self._transition("DESCEND")

        elif self._state == "LIFT":
            if target_pos is not None:
                # Lift vertically toward the target height first; keep the
                # horizontal position over the object so the grasp is not sheared.
                target = target_pos.clone()
                target[2] += self._lift_height
                if object_pos is not None:
                    target[:2] = object_pos[:2]
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            # Cap the vertical acceleration to avoid pulling the object out of the
            # grip during the lift.
            lift_max_delta = self._lift_max_delta
            if lift_max_delta is None or lift_max_delta > self._max_lift_delta_z:
                lift_max_delta = self._max_lift_delta_z
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=self._lift_horizontal_scale,
                max_delta=lift_max_delta,
            )
            action = self._set_gripper(action, open=False)
            # Transition when high enough; horizontal/rotational alignment is
            # handled in ALIGN to avoid dragging the object during lift.
            height_ok = eef_pos[2] >= target[2] - 0.03
            if height_ok:
                if self._verify_object_following_steps > 0 and not self._object_following_verified:
                    self._lift_start_object_pos = object_pos.clone()
                    self._lift_start_eef_pos = eef_pos.clone()
                    self._transition("VERIFY_OBJECT_FOLLOWING")
                elif self._reorient_before_align and target_quat is not None and not self._skip_broken_yaw_control:
                    self._transition("REORIENT")
                else:
                    self._transition("ALIGN")

        elif self._state == "VERIFY_OBJECT_FOLLOWING":
            # Brief hold at the current pose to verify the object is moving with
            # the gripper before continuing.  This catches slips early instead of
            # waiting for a later drop.
            target = eef_pos.clone()
            target[2] += self._lift_height
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=0.0,
                max_delta=self._max_lift_delta_z,
            )
            action = self._set_gripper(action, open=False)
            object_following = False
            if self._lift_start_object_pos is not None and self._lift_start_eef_pos is not None:
                object_delta = torch.norm(object_pos - self._lift_start_object_pos)
                eef_delta = torch.norm(eef_pos - self._lift_start_eef_pos)
                relative_delta = torch.norm(object_pos - eef_pos)
                object_following = (
                    object_delta > eef_delta * 0.3
                    and relative_delta < self._object_following_distance_threshold
                )
            if self._state_step >= self._verify_object_following_steps:
                self._object_following_verified = True
                if object_following:
                    if self._reorient_before_align and target_quat is not None and not self._skip_broken_yaw_control:
                        self._transition("REORIENT")
                    else:
                        self._transition("ALIGN")
                else:
                    # Object did not follow; drop back to HOLD and log the failure.
                    self._transition("HOLD")

        elif self._state == "REORIENT":
            # Keep the object high and over the target, but rotate the gripper (and
            # the grasped object) toward the target orientation before final
            # alignment.  This avoids dragging the object during lift.
            if self._skip_broken_yaw_control:
                self._transition("ALIGN")
            else:
                if target_pos is not None:
                    target = target_pos.clone()
                else:
                    target = object_pos.clone()
                target[2] += self._reorient_height_offset
                self._apply_position(
                    action,
                    eef_pos,
                    eef_quat,
                    target,
                    kp_multiplier=self._align_kp_multiplier,
                    horizontal_scale=0.0,
                    max_delta=self._align_max_delta,
                )
                # If pre-grasp yaw alignment v2 was used, most of the required
                # yaw has already been commanded before the grasp.  Limit the
                # in-hand rotation to the residual fraction to reduce slip.
                reorient_target_quat = target_quat
                if (
                    self._pre_grasp_yaw_align_v2
                    and target_quat is not None
                    and eef_quat is not None
                    and self._post_grasp_yaw_residual_fraction < 1.0
                ):
                    current_yaw = self._quat_to_yaw(eef_quat)
                    final_yaw = self._quat_to_yaw(target_quat)
                    residual_yaw = current_yaw + self._post_grasp_yaw_residual_fraction * self._angle_diff(final_yaw, current_yaw)
                    reorient_target_quat = torch.tensor(
                        [0.0, 0.0, math.sin(residual_yaw / 2.0), math.cos(residual_yaw / 2.0)],
                        device=device,
                        dtype=eef_quat.dtype,
                    )
                self._apply_orientation(action, eef_quat, reorient_target_quat)
                action = self._set_gripper(action, open=False)
                if self._orientation_aligned(eef_quat, reorient_target_quat):
                    if self._stabilize_steps_after_yaw > 0:
                        self._transition("STABILIZE")
                    else:
                        self._transition("ALIGN")

        elif self._state == "STABILIZE":
            # Hold the gripper closed and steady after reorientation to let the
            # grasp settle before alignment.
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._reorient_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp_multiplier,
                horizontal_scale=0.0,
                max_delta=self._align_max_delta * 0.5,
            )
            action = self._set_gripper(action, open=False)
            if self._state_step >= self._stabilize_steps_after_yaw:
                self._transition("ALIGN")

        elif self._state == "ALIGN":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp_multiplier,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._align_max_delta,
            )
            self._apply_orientation(action, eef_quat, target_quat)
            action = self._set_gripper(action, open=False)
            # Require the object (not just the eef) to be at the target before
            # declaring alignment, otherwise a fast eef motion can leave the
            # object behind or cause it to slip.
            if target_pos is not None and object_pos is not None:
                position_ok = torch.norm(target - object_pos) < self._success_threshold
            else:
                position_ok = torch.norm(target - eef_pos) < self._success_threshold
            orientation_ok = (
                self._orientation_aligned(eef_quat, target_quat)
                or not self._require_orientation_alignment
            )
            if position_ok and orientation_ok:
                if self._release_at_target:
                    self._transition("RELEASE")
                else:
                    self._transition("HOLD")

        elif self._state == "RELEASE":
            # In absolute mode a zero action vector means "move to the origin", so
            # hold the current pose while the gripper opens.
            if not self._relative_mode and eef_pos is not None:
                self._apply_position(action, eef_pos, eef_quat, eef_pos)
            action = self._set_gripper(action, open=True)
            if self._state_step >= self._min_release_steps:
                self._transition("HOLD")

        elif self._state == "HOLD":
            # Goal-pose tasks normally keep the object grasped at the target pose.
            # Only open the gripper if an explicit release was requested/scheduled.
            # In absolute mode we must command the current pose to avoid drifting
            # toward the origin.
            if not self._relative_mode and eef_pos is not None:
                self._apply_position(action, eef_pos, eef_quat, eef_pos)
            if self._release_at_target:
                action = self._set_gripper(action, open=True)
            else:
                action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        object_yaw = self._extract_object_yaw(env, device)
        target_yaw = None
        if target_quat is not None and target_quat.numel() >= 4:
            target_yaw = self._quat_to_yaw(target_quat)
        object_yaw_error = None
        if object_yaw is not None and target_yaw is not None:
            object_yaw_error = self._angle_diff(target_yaw, object_yaw)

        # End-effector orientation and yaw tracking.
        eef_roll = eef_pitch = eef_yaw = None
        if eef_quat is not None and eef_quat.numel() >= 4:
            eef_roll, eef_pitch, eef_yaw = self._quat_to_rpy(eef_quat)

        # Desired eef yaw depends on the current phase.
        desired_eef_yaw = None
        if self._state == "PRE_GRASP_ORIENT" and object_yaw is not None:
            desired_eef_yaw = object_yaw + self._grasp_target_yaw_offset
        elif target_yaw is not None:
            desired_eef_yaw = target_yaw
        elif object_yaw is not None:
            desired_eef_yaw = object_yaw

        eef_yaw_error = None
        if eef_yaw is not None and desired_eef_yaw is not None:
            eef_yaw_error = self._angle_diff(desired_eef_yaw, eef_yaw)

        # Rotational action components for axis calibration.
        action_rot_x = action_rot_y = action_rot_z = None
        if action.shape[-1] >= 6:
            action_rot_x = float(action[..., 3].item())
            action_rot_y = float(action[..., 4].item())
            action_rot_z = float(action[..., 5].item())

        _append_trace({
            "episode": self._episode_idx,
            "step": step,
            "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
            "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
            "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
            "eef_qx": float(eef_quat[0].item()) if eef_quat is not None and eef_quat.numel() >= 4 else None,
            "eef_qy": float(eef_quat[1].item()) if eef_quat is not None and eef_quat.numel() >= 4 else None,
            "eef_qz": float(eef_quat[2].item()) if eef_quat is not None and eef_quat.numel() >= 4 else None,
            "eef_qw": float(eef_quat[3].item()) if eef_quat is not None and eef_quat.numel() >= 4 else None,
            "eef_roll": eef_roll,
            "eef_pitch": eef_pitch,
            "eef_yaw": eef_yaw,
            "desired_eef_yaw": desired_eef_yaw,
            "eef_yaw_error": eef_yaw_error,
            "object_x": float(object_pos[0].item()) if object_pos is not None else None,
            "object_y": float(object_pos[1].item()) if object_pos is not None else None,
            "object_z": float(object_pos[2].item()) if object_pos is not None else None,
            "object_yaw": float(object_yaw) if object_yaw is not None else None,
            "target_yaw": float(target_yaw) if target_yaw is not None else None,
            "object_yaw_error": object_yaw_error,
            # Deprecated alias kept for backward compatibility with older
            # reports; new analysis should use object_yaw_error.
            "orientation_error": object_yaw_error,
            "target_x": float(target_pos[0].item()) if target_pos is not None else None,
            "target_y": float(target_pos[1].item()) if target_pos is not None else None,
            "target_z": float(target_pos[2].item()) if target_pos is not None else None,
            "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
            "action_norm": float(torch.linalg.norm(action).item()),
            "action_rot_x": action_rot_x,
            "action_rot_y": action_rot_y,
            "action_rot_z": action_rot_z,
            "contact_proxy": self._contact_proxy,
            "regrasp_attempt": self._regrasp_attempt_count,
            "grasp_effective": self._grasp_effective,
            "lift_response_z": self._lift_response_z,
            "phase": self._state,
            **(self._last_gate_diagnostics or {}),
        })

        return action

    def _apply_position(
        self,
        action: torch.Tensor,
        eef_pos: torch.Tensor | None,
        eef_quat: torch.Tensor | None,
        target: torch.Tensor,
        kp_multiplier: float = 1.0,
        horizontal_scale: float = 1.0,
        max_delta: float | None = None,
    ) -> None:
        """Write a position command into ``action`` using body-frame mapping.

        The cube_goal_pose environment leaves the Franka controller in relative
        mode with the end-effector yawed ~180° at reset. World-frame deltas must
        be rotated into the end-effector body frame before being written as
        relative-pose actions; otherwise the arm moves away from the object.
        """
        if eef_pos is None:
            return
        delta_world = self._kp * kp_multiplier * (target - eef_pos)
        if horizontal_scale != 1.0:
            delta_world[:2] *= horizontal_scale

        if max_delta is None:
            max_delta = 0.5 if self._relative_mode else 0.1
        delta_world = torch.clamp(delta_world, -max_delta, max_delta)

        if self._relative_mode:
            body_delta = self._world_delta_to_body(delta_world, eef_quat)
            cmd = body_delta / self._action_scale
            action[..., :3] = torch.clamp(cmd, -1.0, 1.0)
            if action.shape[-1] >= 6:
                action[..., 3:6] = 0.0
        else:
            action[..., :3] = eef_pos + delta_world
            if action.shape[-1] >= 7:
                quat = (
                    eef_quat
                    if eef_quat is not None and eef_quat.numel() >= 4
                    else torch.tensor([0.0, 0.0, 0.0, 1.0], device=action.device, dtype=action.dtype)
                )
                action[..., 3:7] = quat[:4]

    def _world_delta_to_body(
        self, delta_world: torch.Tensor, eef_quat: torch.Tensor | None
    ) -> torch.Tensor:
        """Rotate a world-frame delta into the end-effector body frame."""
        if eef_quat is None or eef_quat.numel() < 4:
            return delta_world
        try:
            from isaaclab.utils.math import quat_rotate_inverse

            return quat_rotate_inverse(eef_quat.unsqueeze(0), delta_world.unsqueeze(0)).squeeze()
        except Exception:
            return delta_world

    def _extract_target_quat_world(
        self, observation: GymSpacesDict, env: gym.Env, device: torch.device
    ) -> torch.Tensor | None:
        """Read the command target quaternion and transform it to the world frame."""
        root_pos, root_quat = None, None
        for cmd_name in ("object_pose", "pose_command", "target_pose"):
            try:
                cm = env.unwrapped.command_manager
                cmd = cm.get_command(cmd_name)
                cmd_t = torch.as_tensor(cmd, device=device).squeeze()
                if cmd_t.numel() < 7:
                    continue
                des_pos_b = cmd_t[:3]
                des_quat_b = cmd_t[3:7]
                if root_pos is None:
                    root_pos, root_quat = self._extract_robot_root(env, device)
                if root_pos is not None and root_quat is not None:
                    from isaaclab.utils.math import combine_frame_transforms

                    _target_w, target_q = combine_frame_transforms(
                        root_pos.unsqueeze(0),
                        root_quat.unsqueeze(0),
                        des_pos_b.unsqueeze(0),
                        des_quat_b.unsqueeze(0),
                    )
                    return target_q.squeeze()
            except Exception:
                continue
        return None

    def _extract_object_yaw(
        self, env: gym.Env, device: torch.device
    ) -> float | None:
        """Return the object's world-frame yaw from the scene, if available."""
        try:
            scene = getattr(env.unwrapped, "scene", None)
            if scene is None:
                return None
            for key in ("dex_cube", "object", "cube"):
                if key not in scene.keys():
                    continue
                obj = scene[key]
                data = getattr(obj, "data", None)
                if data is not None and hasattr(data, "root_quat_w"):
                    quat = data.root_quat_w.squeeze().to(device)
                    if quat.ndim > 1:
                        quat = quat[0]
                    if quat.numel() >= 4:
                        return self._quat_to_yaw(quat)
        except Exception:
            pass
        return None

    def _get_eef_pose_base(
        self, env: gym.Env, device: torch.device
    ) -> tuple[torch.Tensor | None, torch.Tensor | None]:
        """Return end-effector pose in the action term's base frame.

        Absolute-pose controllers (``franka_ik_abs``) expect position and
        quaternion commands relative to the robot base frame.  This mirrors the
        conversion used by ``RotationalCalibrationPolicy``.
        """
        try:
            am = env.unwrapped.action_manager
            arm_action = am.get_term("arm_action")
            if arm_action is not None and hasattr(arm_action, "_compute_frame_pose"):
                pose_b, quat_b = arm_action._compute_frame_pose()
                pos_b = pose_b.squeeze().to(device)
                quat_b = quat_b.squeeze().to(device)
                if pos_b.ndim > 1:
                    pos_b = pos_b[0]
                if quat_b.ndim > 1:
                    quat_b = quat_b[0]
                return pos_b, quat_b
        except Exception:
            pass
        return None, None

    def _world_pose_to_base(
        self,
        pos_w: torch.Tensor,
        quat_w: torch.Tensor,
        env: gym.Env,
        device: torch.device,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Convert a world-frame pose to the robot base frame."""
        root_pos, root_quat = self._extract_robot_root(env, device)
        if root_pos is None or root_quat is None:
            return pos_w, quat_w
        try:
            from isaaclab.utils.math import subtract_frame_transforms

            pos_b, quat_b = subtract_frame_transforms(
                root_pos.unsqueeze(0),
                root_quat.unsqueeze(0),
                pos_w.unsqueeze(0),
                quat_w.unsqueeze(0),
            )
            return pos_b.squeeze(), quat_b.squeeze()
        except Exception:
            return pos_w, quat_w

    def _apply_orientation(
        self,
        action: torch.Tensor,
        eef_quat: torch.Tensor | None,
        target_quat: torch.Tensor | None,
    ) -> None:
        """Write an orientation command into ``action``."""
        if target_quat is None:
            return
        if self._skip_broken_yaw_control:
            return
        if self._use_quaternion_orientation_target and action.shape[-1] >= 7:
            self._apply_orientation_quaternion(action, eef_quat, target_quat)
        elif self._relative_mode:
            # Relative controllers: command a yaw correction.
            if eef_quat is None:
                return
            try:
                yaw_current = self._quat_to_yaw(eef_quat)
                yaw_target = self._quat_to_yaw(target_quat)
                yaw_err = self._angle_diff(yaw_target, yaw_current)
                yaw_err = torch.clamp(torch.as_tensor(yaw_err, device=action.device), -self._yaw_step_size, self._yaw_step_size)
                action[..., 5] = torch.clamp(yaw_err * 2.0, -1.0, 1.0)
            except Exception:
                pass
        else:
            # Absolute mode: command the target quaternion directly. Clamp the
            # rotation step to yaw_step_size to limit roll/pitch coupling during
            # large reorientation.
            clamped = self._clamp_orientation_target(eef_quat, target_quat)
            if clamped is not None:
                action[..., 3:7] = clamped[:4]

    def _clamp_orientation_target(
        self,
        eef_quat: torch.Tensor | None,
        target_quat: torch.Tensor | None,
    ) -> torch.Tensor | None:
        """Return a target quaternion at most ``_yaw_step_size`` from ``eef_quat``.

        Computes the relative rotation from current to target, clamps its angle,
        and multiplies back by the current quaternion. This gives an absolute
        target that the controller can reach in one step without introducing
        large coupled roll/pitch motion.
        """
        if eef_quat is None or target_quat is None:
            return target_quat
        try:
            # Relative quaternion: q_rel = q_target * conj(q_current) (x,y,z,w).
            qw = eef_quat[3]
            qx = -eef_quat[0]
            qy = -eef_quat[1]
            qz = -eef_quat[2]
            tw = target_quat[3] * qw - target_quat[0] * qx - target_quat[1] * qy - target_quat[2] * qz
            tx = target_quat[0] * qw + target_quat[3] * qx + target_quat[1] * qz - target_quat[2] * qy
            ty = target_quat[1] * qw + target_quat[3] * qy + target_quat[2] * qx - target_quat[0] * qz
            tz = target_quat[2] * qw + target_quat[3] * qz + target_quat[0] * qy - target_quat[1] * qx
            rel = torch.stack([tx, ty, tz, tw], dim=0)
            rel = rel / (torch.norm(rel) + 1e-8)

            angle = 2.0 * torch.acos(torch.clamp(rel[3], -1.0, 1.0))
            if angle <= self._yaw_step_size:
                return target_quat

            scale = self._yaw_step_size / (angle + 1e-8)
            s = torch.sin(scale * angle / 2.0)
            denom = torch.sin(angle / 2.0) + 1e-8
            rel_scaled = torch.stack(
                [
                    rel[0] / denom * s,
                    rel[1] / denom * s,
                    rel[2] / denom * s,
                    torch.cos(scale * angle / 2.0),
                ],
                dim=0,
            )

            # target_clamped = rel_scaled * current.
            cw = eef_quat[3]
            cx = eef_quat[0]
            cy = eef_quat[1]
            cz = eef_quat[2]
            rw = rel_scaled[3]
            rx = rel_scaled[0]
            ry = rel_scaled[1]
            rz = rel_scaled[2]
            tx = rw * cx + rx * cw + ry * cz - rz * cy
            ty = rw * cy - rx * cz + ry * cw + rz * cx
            tz = rw * cz + rx * cy - ry * cx + rz * cw
            tw = rw * cw - rx * cx - ry * cy - rz * cz
            return torch.stack([tx, ty, tz, tw], dim=0)
        except Exception:
            return target_quat

    def _apply_orientation_quaternion(
        self,
        action: torch.Tensor,
        eef_quat: torch.Tensor | None,
        target_quat: torch.Tensor | None,
    ) -> None:
        """Command orientation as a (clamped) delta quaternion.

        The relative-mode controller interprets ``action[..., 3:7]`` as a delta
        quaternion when the action space is 8-dimensional.  We compute the delta
        from the current end-effector orientation to the target orientation,
        clamp the rotation magnitude to ``_yaw_step_size`` to avoid slip, and
        write it into the action.
        """
        if eef_quat is None or target_quat is None:
            return
        try:
            # Compute relative quaternion: q_rel = q_target * conj(q_current).
            qw = eef_quat[3]
            qx = -eef_quat[0]
            qy = -eef_quat[1]
            qz = -eef_quat[2]
            tw = target_quat[3] * qw - target_quat[0] * qx - target_quat[1] * qy - target_quat[2] * qz
            tx = target_quat[0] * qw + target_quat[3] * qx + target_quat[1] * qz - target_quat[2] * qy
            ty = target_quat[1] * qw + target_quat[3] * qy + target_quat[2] * qx - target_quat[0] * qz
            tz = target_quat[2] * qw + target_quat[3] * qz + target_quat[0] * qy - target_quat[1] * qx
            rel = torch.stack([tx, ty, tz, tw], dim=0)
            rel = rel / (torch.norm(rel) + 1e-8)

            # Clamp the rotation angle to yaw_step_size.
            angle = 2.0 * torch.acos(torch.clamp(rel[3], -1.0, 1.0))
            if angle > self._yaw_step_size:
                scale = self._yaw_step_size / (angle + 1e-8)
                s = torch.sin(scale * angle / 2.0)
                rel = torch.stack(
                    [rel[0] / (torch.sin(angle / 2.0) + 1e-8) * s,
                     rel[1] / (torch.sin(angle / 2.0) + 1e-8) * s,
                     rel[2] / (torch.sin(angle / 2.0) + 1e-8) * s,
                     torch.cos(scale * angle / 2.0)],
                    dim=0,
                )

            action[..., 3:7] = rel[:4]
        except Exception:
            pass

    def _orientation_aligned(
        self, eef_quat: torch.Tensor | None, target_quat: torch.Tensor | None
    ) -> bool:
        if target_quat is None or eef_quat is None:
            return True
        try:
            dot = float(torch.abs(torch.sum(eef_quat * target_quat)).item())
            dot = min(1.0, max(0.0, dot))
            angle = 2.0 * math.acos(dot)
            return angle < self._orientation_threshold
        except Exception:
            return True

    def _classify_contact_proxy(
        self,
        gripper_pos: torch.Tensor | None,
        object_pos: torch.Tensor | None,
        eef_pos: torch.Tensor | None,
    ) -> str:
        """Infer contact quality from gripper width and object motion.

        This is a structural diagnostic for FailureToHint v3.1.  It does not
        require force/tactile sensors; it uses the gripper aperture and the
        relative object/eef displacement during the close phase.
        """
        if gripper_pos is None or object_pos is None or eef_pos is None:
            return "unknown"
        width = float(gripper_pos.item())
        # A still-open gripper after a close attempt means the fingers never
        # encountered the object.
        if width > 0.08:
            return "no_contact"
        object_eef_dist = float(torch.norm(object_pos - eef_pos).item())
        if self._grasp_start_object_pos is not None and self._grasp_start_eef_pos is not None:
            object_delta = float(torch.norm(object_pos - self._grasp_start_object_pos).item())
            start_dist = float(torch.norm(self._grasp_start_object_pos - self._grasp_start_eef_pos).item())
            # If the object moved away from the gripper by more than a small
            # margin, the close action pushed it out of the grasp.
            if object_delta > 0.02 or object_eef_dist > start_dist + 0.02:
                return "pushed_away"
            # Gripper blocked (aperture larger than empty-close threshold) and
            # the object stayed close: some contact exists.
            if width > self._gripper_close_threshold * 1.5:
                return "likely_contact"
            # Aperture is small but the object did not move: weak/frictional
            # contact that may not support a lift.
            return "weak_contact_no_lift"
        # Without the start-of-grasp reference, fall back to a distance heuristic.
        if object_eef_dist < self._grasp_dist_threshold + 0.01 and width > self._gripper_close_threshold * 1.5:
            return "likely_contact"
        return "unknown"

    @staticmethod
    def _quat_to_yaw(q: torch.Tensor) -> float:
        return _quat_to_yaw(q)

    @staticmethod
    def _quat_to_rpy(q: torch.Tensor) -> tuple[float, float, float]:
        return _quat_to_rpy(q)

    @staticmethod
    def _angle_diff(target: float, current: float) -> float:
        return _angle_diff(target, current)

    def _apply_geometry_adaptation(self, geometry: Any) -> None:
        """Scale policy thresholds to the object's actual geometry.

        Called once at first step (or at construction if a declared geometry is
        provided).  The skill-hint overrides are applied *before* this method,
        so geometry adaptation refines rather than replaces user hints.
        """
        if ObjectGeometryAdapter is None or AdaptedPolicyParams is None:
            return
        try:
            params = self._object_geometry_adapter.adapt(geometry)
            self._grasp_dist_threshold = params.grasp_dist_threshold
            self._grasp_z_tolerance = params.grasp_z_tolerance
            self._approach_offset_z = params.approach_offset_z
            self._lift_height = params.lift_height
            self._gripper_close_threshold = params.gripper_close_threshold
            self._min_grasp_steps = params.min_grasp_steps
            self._object_following_distance_threshold = params.object_following_distance_threshold
            if params.align_max_delta is not None:
                self._align_max_delta = params.align_max_delta
            import sys

            print(
                f"[OBJECT_GEOMETRY] adapted to {geometry.object_name} "
                f"w={geometry.width:.4f} d={geometry.depth:.4f} h={geometry.height:.4f} "
                f"mass={getattr(geometry, 'mass', None)} friction={getattr(geometry, 'static_friction', None)}: "
                f"grasp_dist={self._grasp_dist_threshold:.4f} grasp_z={self._grasp_z_tolerance:.4f} "
                f"approach_z={self._approach_offset_z:.4f} lift_h={self._lift_height:.4f} "
                f"close={self._gripper_close_threshold:.4f} min_grasp={self._min_grasp_steps}",
                file=sys.stderr,
            )
            sys.stderr.flush()
        except Exception as e:
            import sys

            print(f"[OBJECT_GEOMETRY] adaptation failed: {e}", file=sys.stderr)
            sys.stderr.flush()

    def _log_hints(self) -> None:
        import sys

        print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
        print(
            f"[HEURISTIC_SKILL_HINTS] params: approach_z={self._approach_offset_z:.4f} "
            f"grasp_z={self._grasp_offset_z:.4f} lift_h={self._lift_height:.4f} "
            f"align_h={self._align_height_offset:.4f} kp={self._kp:.4f} "
            f"grasp_dist={self._grasp_dist_threshold:.4f} min_grasp={self._min_grasp_steps} "
            f"min_release={self._min_release_steps} orient_thr={self._orientation_threshold:.4f}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        super().reset(env_ids)
        self._object_following_verified = False
        self._lift_start_object_pos = None
        self._lift_start_eef_pos = None
        self._initial_object_pos = None
        self._reachability_risk = None
        # Clear the child shadow of _last_gate_diagnostics so that stale DESCEND
        # diagnostics from a previous episode do not overwrite the phase field in
        # trace records of the next episode.
        self._last_gate_diagnostics = None
        self._seed_randomization_done = False
        # Reset structural regrasp / contact-diagnosis state for each episode.
        self._regrasp_attempt_count = 0
        self._grasp_start_object_pos = None
        self._grasp_start_eef_pos = None
        self._lift_verify_start_object_z = None
        self._contact_proxy = "unknown"
        self._grasp_effective = False
        self._lift_response_z = 0.0

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoGoalPosePolicy":
        return HeuristicServoGoalPosePolicy(HeuristicServoGoalPosePolicyArgs.from_cli_args(args))


class HeuristicServoPickPolicy(HeuristicServoLiftPolicy):
    """Closed-loop servo heuristic for pick/place tasks with post-lift alignment.

    Extends the lift state machine with explicit ALIGN, SLOW_ALIGN, and
    HOLD_AT_TARGET phases.  After lifting to the command target height the
    policy moves horizontally to the target, slows down as it approaches, and
    then holds the object at the target for a configurable number of steps.
    This addresses the ``target_not_reached_after_lift`` success gap observed
    on ``pick_object``.
    """

    name = "heuristic_servo_pick"
    config_class = HeuristicServoPickPolicyArgs

    def __init__(self, config: HeuristicServoPickPolicyArgs):
        super().__init__(config)
        self._enable_align_phase = config.enable_align_phase
        self._align_kp = config.align_kp
        self._final_align_speed = config.final_align_speed
        self._hold_steps = config.hold_steps
        self._align_height_offset = config.align_height_offset
        self._settle_before_success = config.settle_before_success
        self._near_target_gain = config.near_target_gain
        self._align_max_delta = config.align_max_delta
        self._slow_align_max_delta = config.slow_align_max_delta
        self._align_horizontal_scale = config.align_horizontal_scale
        self._slow_align_threshold = config.slow_align_threshold

        # Signature-driven hint effects.
        if "precision_target_tracking" in self._skill_hints:
            self._align_kp *= 1.2
            self._success_threshold = max(0.03, self._success_threshold * 0.8)
        if "slow_final_align" in self._skill_hints:
            self._final_align_speed *= 0.6
            if self._align_max_delta is not None:
                self._align_max_delta *= 0.7
            if self._slow_align_max_delta is not None:
                self._slow_align_max_delta *= 0.7
        if "hold_at_target" in self._skill_hints:
            self._hold_steps += 15
        if "reduce_near_target_gain" in self._skill_hints:
            self._near_target_gain *= 0.6
        if "settle_before_success_check" in self._skill_hints:
            self._settle_before_success = True

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1
        self._state_step += 1

        if step == 0 and self._skill_hints:
            self._log_hints()

        if self._relative_mode is None:
            self._infer_controller_mode(env)

        eef_pos, eef_quat, object_pos, gripper_pos, target_pos = self._extract_state(observation, env, device)

        if object_pos is None:
            # Fallback open-loop sequence when observation is missing.
            if step < 50:
                action[..., 2] = -0.04
                action = self._set_gripper(action, open=True)
            else:
                action[..., 2] = 0.04
                action = self._set_gripper(action, open=False)
            return action

        if self._state == "APPROACH":
            target = object_pos.clone()
            target[2] += self._approach_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            horiz = torch.norm(object_pos[:2] - eef_pos[:2])
            z_err = abs(eef_pos[2] - target[2])
            if horiz < self._approach_horizontal_threshold and z_err < self._approach_offset_z * 0.5:
                self._transition("DESCEND")

        elif self._state == "DESCEND":
            target = object_pos.clone()
            target[2] += self._grasp_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            if torch.norm(target - eef_pos) < self._grasp_dist_threshold:
                self._transition("GRASP")

        elif self._state == "GRASP":
            action = self._set_gripper(action, open=False)
            squeeze_deadline = self._min_grasp_steps + self._grasp_squeeze_steps
            if self._state_step >= self._min_grasp_steps:
                if gripper_pos is not None and gripper_pos < self._gripper_close_threshold:
                    self._transition("LIFT")
                elif self._state_step >= squeeze_deadline:
                    self._transition("LIFT")

        elif self._state == "LIFT":
            # Use the command target directly when available (it already encodes
            # the desired lift height / placement pose).  Only fall back to
            # object_pos + lift_height for tasks without an explicit target.
            if target_pos is not None:
                target = target_pos.clone()
                if object_pos is not None:
                    target[:2] = object_pos[:2]
            else:
                target = object_pos.clone()
                target[2] += self._lift_height
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._lift_kp_multiplier,
                horizontal_scale=self._lift_horizontal_scale,
                max_delta=self._lift_max_delta,
            )
            action = self._set_gripper(action, open=False)
            height_ok = eef_pos[2] >= target[2] - 0.03
            if self._enable_align_phase and target_pos is not None:
                if height_ok:
                    self._transition("ALIGN")
            elif height_ok:
                self._transition("HOLD")

        elif self._state == "ALIGN":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            horizontal_dist = torch.norm(target[:2] - object_pos[:2]) if object_pos is not None else torch.norm(target[:2] - eef_pos[:2])
            # Reduce gain when very close to avoid overshoot.
            kp = self._align_kp * (self._near_target_gain if horizontal_dist < self._slow_align_threshold else 1.0)
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=kp,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._align_max_delta,
            )
            action = self._set_gripper(action, open=False)
            if horizontal_dist < self._success_threshold:
                if self._settle_before_success:
                    self._transition("SLOW_ALIGN")
                else:
                    self._transition("HOLD_AT_TARGET")

        elif self._state == "SLOW_ALIGN":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp * self._near_target_gain,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._slow_align_max_delta,
            )
            action = self._set_gripper(action, open=False)
            if self._state_step >= max(1, int(self._hold_steps * 0.25)):
                self._transition("HOLD_AT_TARGET")

        elif self._state == "HOLD_AT_TARGET":
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp * self._near_target_gain,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._slow_align_max_delta,
            )
            action = self._set_gripper(action, open=False)
            if self._state_step >= self._hold_steps:
                self._transition("VERIFY_SUCCESS")

        elif self._state == "VERIFY_SUCCESS":
            # Keep the object at the target and let the environment register success.
            if target_pos is not None:
                target = target_pos.clone()
            else:
                target = object_pos.clone()
            target[2] += self._align_height_offset
            self._apply_position(
                action,
                eef_pos,
                eef_quat,
                target,
                kp_multiplier=self._align_kp * self._near_target_gain,
                horizontal_scale=self._align_horizontal_scale,
                max_delta=self._slow_align_max_delta,
            )
            action = self._set_gripper(action, open=False)

        elif self._state == "HOLD":
            action = self._set_gripper(action, open=False)

        if self._state_step > self._max_state_steps:
            self._transition("HOLD")

        if object_pos is not None:
            _append_trace({
                "episode": self._episode_idx,
                "step": step,
                "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
                "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
                "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
                "object_x": float(object_pos[0].item()),
                "object_y": float(object_pos[1].item()),
                "object_z": float(object_pos[2].item()),
                "target_x": float(target_pos[0].item()) if target_pos is not None else None,
                "target_y": float(target_pos[1].item()) if target_pos is not None else None,
                "target_z": float(target_pos[2].item()) if target_pos is not None else None,
                "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
                "action_norm": float(torch.linalg.norm(action).item()),
                "phase": self._state,
            })

        return action

    def _log_hints(self) -> None:
        import sys
        print(f"[HEURISTIC_SKILL_HINTS] consumed: {sorted(self._skill_hints)}", file=sys.stderr)
        print(
            f"[HEURISTIC_SKILL_HINTS] params: approach_z={self._approach_offset_z:.4f} "
            f"grasp_z={self._grasp_offset_z:.4f} lift_h={self._lift_height:.4f} "
            f"align_kp={self._align_kp:.4f} align_max_delta={self._align_max_delta} "
            f"hold_steps={self._hold_steps} settle={self._settle_before_success}",
            file=sys.stderr,
        )
        sys.stderr.flush()

    @staticmethod
    def from_args(args: argparse.Namespace) -> "HeuristicServoPickPolicy":
        return HeuristicServoPickPolicy(HeuristicServoPickPolicyArgs.from_cli_args(args))


class CheatLiftPolicy(PolicyBase):
    """Cheat policy for lift_object: teleport the object to a lifted pose.

    This is NOT a real robot policy; it directly manipulates the object's
    root pose in simulation to verify that the Arena eval pipeline can
    report a non-zero success_rate. Used as a sanity-check baseline only.
    """

    name = "cheat_lift"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._cheat_done = False

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        # Close the gripper for the remainder of the episode.
        action[..., -1] = -1.0
        step = self._step
        self._step += 1

        if step == 0:
            import sys
            print(f"[CHEAT_LIFT] get_action called, action_space={env.action_space.shape}", file=sys.stderr)
            sys.stderr.flush()

        if step >= 2:
            try:
                import sys

                scene = env.unwrapped.scene
                obj = None
                for key in scene.keys():
                    key_str = str(key)
                    if key_str in ("object", "dex_cube", "cube"):
                        obj = scene[key_str]
                        break

                # The RL task success is defined as object within tolerance of the
                # generated command target pose. Read the target from task_obs.
                target_pos = None
                if isinstance(observation, dict) and "task_obs" in observation:
                    task_obs = observation["task_obs"]
                    if hasattr(task_obs, "squeeze"):
                        task_obs = task_obs.squeeze()
                    if task_obs.numel() >= 3:
                        target_pos = task_obs[:3]

                if obj is not None and target_pos is not None:
                    device = target_pos.device
                    origin = scene.env_origins[0:1] if hasattr(scene, "env_origins") else torch.zeros((1, 3), device=device)
                    target_quat = torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=device)
                    zero_vel = torch.zeros((1, 6), device=device)
                    root_pose = torch.cat([target_pos.unsqueeze(0) + origin, target_quat], dim=-1)
                    obj.write_root_pose_to_sim(root_pose)
                    obj.write_root_velocity_to_sim(zero_vel)
                    if step == 2:
                        print(f"[CHEAT_LIFT] Holding object at command target {target_pos.tolist()}", file=sys.stderr)
                        sys.stderr.flush()
            except Exception as e:
                import sys
                print(f"[CHEAT_LIFT] Error during teleport: {e}", file=sys.stderr)
                sys.stderr.flush()

        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "CheatLiftPolicy":
        return CheatLiftPolicy(HeuristicLiftPolicyArgs.from_cli_args(args))


class CubeGoalPoseHeuristicPolicy(PolicyBase):
    """Heuristic for cube_goal_pose: grasp, lift, and rotate yaw 90°.

    CRITICAL DISCOVERY from Docker stderr:
      - action_space.shape = (1, 7)  [not 8-dim quaternion]
      - action_space has NO bounds (low=-inf, high=inf)
      - observation has NO object_pos / object_quat
      - eef initial yaw ≈ 180° (quat z≈1, w≈0, format x,y,z,w)
      - controller position response is heavily damped (~3% of action)
      - orientation control shows ZERO response so far

    This version aggressively increases delta_z to overcome damping and
    probes env config on first step.
    """

    name = "cube_goal_pose_heuristic"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1

        # DRASTIC INCREASE to overcome controller damping/smoothing
        delta_z = 0.8
        target_yaw = 10.0  # very large to test if orientation control is active at all

        # Probe env config on first step
        if step == 0:
            import sys
            uw = env.unwrapped
            print(f"[HEURISTIC_DEBUG] action_space: shape={env.action_space.shape} low={getattr(env.action_space, 'low', 'N/A')} high={getattr(env.action_space, 'high', 'N/A')}", file=sys.stderr)
            print(f"[HEURISTIC_DEBUG] unwrapped type: {type(uw).__name__}", file=sys.stderr)
            if hasattr(uw, "cfg"):
                cfg = uw.cfg
                print(f"[HEURISTIC_DEBUG] env cfg type: {type(cfg).__name__}", file=sys.stderr)
                if hasattr(cfg, "observations"):
                    print(f"[HEURISTIC_DEBUG] observations: {cfg.observations}", file=sys.stderr)
                if hasattr(cfg, "actions"):
                    print(f"[HEURISTIC_DEBUG] actions: {cfg.actions}", file=sys.stderr)
            if isinstance(observation, dict):
                pol = observation.get("policy", observation)
                if isinstance(pol, dict):
                    eef_q = pol.get("eef_quat")
                    eef_p = pol.get("eef_pos")
                    obj_p = pol.get("object_pos")
                    if eef_q is not None:
                        print(f"[HEURISTIC_DEBUG] step=0 eef_quat={eef_q.tolist()} eef_pos={eef_p.tolist() if eef_p is not None else 'N/A'} object_pos={obj_p.tolist() if obj_p is not None else 'N/A'}", file=sys.stderr)
            sys.stderr.flush()

        if step < 100:
            # Phase 1: aggressive descend toward object
            action[..., 2] = -delta_z
            action[..., -1] = 1.0   # gripper open
        elif step < 120:
            # Phase 2: close gripper
            action[..., 2] = 0.0
            action[..., -1] = -1.0  # gripper close
        elif step == 120:
            # Phase 3: single-step rotate + lift
            action[..., 2] = delta_z
            action[..., 5] = target_yaw
            action[..., -1] = -1.0
            import sys
            print(f"[HEURISTIC_DEBUG] step=120 action={action.tolist()}", file=sys.stderr)
            sys.stderr.flush()
        elif step == 121:
            import sys
            if isinstance(observation, dict):
                pol = observation.get("policy", observation)
                if isinstance(pol, dict):
                    eef_q = pol.get("eef_quat")
                    grip = pol.get("gripper_pos")
                    eef_p = pol.get("eef_pos")
                    print(f"[HEURISTIC_DEBUG] step=121 eef_quat={eef_q.tolist() if eef_q is not None else 'N/A'} gripper_pos={grip.tolist() if grip is not None else 'N/A'} eef_pos={eef_p.tolist() if eef_p is not None else 'N/A'}", file=sys.stderr)
                    sys.stderr.flush()
        elif step < 200:
            # Phase 4: continue lifting
            action[..., 2] = delta_z
            action[..., -1] = -1.0
        else:
            # Phase 5: hold
            action[..., 2] = 0.0
            action[..., -1] = -1.0
        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "CubeGoalPoseHeuristicPolicy":
        return CubeGoalPoseHeuristicPolicy(HeuristicLiftPolicyArgs.from_cli_args(args))


class CheatCubeGoalPosePolicy(PolicyBase):
    """Cheat policy: directly teleport the cube to the target pose.

    This is NOT a real robot policy; it uses env.scene physics APIs to
    immediately satisfy goal_pose_task_termination. Used as a baseline to
    verify the Arena eval pipeline can produce non-zero success_rate.
    """

    name = "cheat_cube_goal_pose"
    config_class = HeuristicLiftPolicyArgs

    def __init__(self, config: HeuristicLiftPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._cheat_done = False

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1

        if step == 50 and not self._cheat_done:
            self._cheat_done = True
            try:
                import sys

                from isaaclab.assets import RigidObject

                scene = env.unwrapped.scene
                target_pos = torch.tensor([[0.1, 0.0, 0.3]], device=device)
                target_quat = torch.tensor([[0.0, 0.0, 0.7071, 0.7071]], device=device)
                zero_vel = torch.zeros((1, 6), device=device)

                # Find the cube object dynamically. In different Arena envs the
                # object key may be "object" (lift_object) or "dex_cube"
                # (cube_goal_pose) or another registered name.
                obj = None
                obj_key = None
                for key in scene.keys():
                    key_str = str(key)
                    if key_str in ("object", "dex_cube", "cube"):
                        obj = scene[key_str]
                        obj_key = key_str
                        break
                if obj is None:
                    # Fallback: iterate scene entities and pick a RigidObject
                    # whose name suggests it is the cube.
                    for ent in scene.values():
                        if isinstance(ent, RigidObject):
                            name = getattr(ent, "name", "") or getattr(ent.cfg, "name", "")
                            if "cube" in name.lower() or "object" in name.lower():
                                obj = ent
                                obj_key = name or "unknown"
                                break
                if obj is None:
                    raise KeyError(
                        f"Could not find cube/object in scene. Available keys: {list(scene.keys())}"
                    )
                origin = scene.env_origins[0:1] if hasattr(scene, "env_origins") else torch.zeros((1, 3), device=device)
                root_pose = torch.cat([target_pos + origin, target_quat], dim=-1)
                obj.write_root_pose_to_sim(root_pose)
                obj.write_root_velocity_to_sim(zero_vel)
                print(f"[CHEAT] Teleported '{obj_key}' to target pose at step {step}", file=sys.stderr)
                sys.stderr.flush()
            except Exception as e:
                import sys

                print(f"[CHEAT] Error during teleport: {e}", file=sys.stderr)
                sys.stderr.flush()

        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._cheat_done = False

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "CheatCubeGoalPosePolicy":
        return CheatCubeGoalPosePolicy(HeuristicLiftPolicyArgs.from_cli_args(args))


@dataclass
class ActionCalibrationPolicyArgs:
    """Configuration for the action-response calibration policy."""

    skill_hints: list[str] | None = None
    calibration_axis: int = 0  # 0=x, 1=y, 2=z
    calibration_sign: float = 1.0
    calibration_magnitude: float = 0.5

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "ActionCalibrationPolicyArgs":
        return cls(
            skill_hints=getattr(args, "skill_hints", None),
            calibration_axis=getattr(args, "calibration_axis", 0),
            calibration_sign=getattr(args, "calibration_sign", 1.0),
            calibration_magnitude=getattr(args, "calibration_magnitude", 0.5),
        )


class ActionCalibrationPolicy(PolicyBase):
    """Fixed-action calibration policy for estimating action->world response.

    Commands a constant delta on a single axis and records the end-effector
    displacement. Used by ``run_action_calibration.py``.
    """

    name = "action_calibration"
    config_class = ActionCalibrationPolicyArgs

    def __init__(self, config: ActionCalibrationPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._axis = int(config.calibration_axis)
        self._sign = float(config.calibration_sign)
        self._magnitude = float(config.calibration_magnitude)
        self._episode_idx = 0
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        action[..., self._axis] = self._sign * self._magnitude
        # Keep gripper open/neutral.
        if action.shape[-1] >= 7:
            action[..., -1] = 1.0

        # Record eef position for calibration analysis.
        try:
            eef_pos = None
            scene = env.unwrapped.scene
            if "ee_frame" in scene.keys():
                data = scene["ee_frame"].data
                for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                    if hasattr(data, attr):
                        pos = getattr(data, attr).squeeze().to(device)
                        if pos.ndim > 1:
                            pos = pos[0]
                        if pos.numel() >= 3:
                            eef_pos = pos
                            break
            if eef_pos is not None:
                _append_trace({
                    "episode": self._episode_idx,
                    "step": self._step,
                    "eef_x": float(eef_pos[0].item()),
                    "eef_y": float(eef_pos[1].item()),
                    "eef_z": float(eef_pos[2].item()),
                    "action_axis": self._axis,
                    "action_sign": self._sign,
                    "action_magnitude": self._magnitude,
                    "action_norm": float(torch.linalg.norm(action).item()),
                })
        except Exception:
            pass

        self._step += 1
        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._episode_idx += 1

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "ActionCalibrationPolicy":
        return ActionCalibrationPolicy(ActionCalibrationPolicyArgs.from_cli_args(args))


@dataclass
class GripperCalibrationPolicyArgs:
    """Configuration for gripper empty/blocked-close calibration."""

    skill_hints: list[str] | None = None
    scenario: str = "empty_close"  # empty_close | blocked_close
    close_command: float = -1.0
    close_steps: int = 100
    approach_offset_z: float = 0.12
    grasp_offset_z: float = 0.0
    kp: float = 5.0
    grasp_dist_threshold: float = 0.03

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "GripperCalibrationPolicyArgs":
        return cls(
            skill_hints=getattr(args, "skill_hints", None),
            scenario=getattr(args, "scenario", "empty_close"),
            close_command=float(getattr(args, "close_command", -1.0)),
            close_steps=int(getattr(args, "close_steps", 100)),
            approach_offset_z=float(getattr(args, "approach_offset_z", 0.12)),
            grasp_offset_z=float(getattr(args, "grasp_offset_z", 0.0)),
            kp=float(getattr(args, "kp", 5.0)),
            grasp_dist_threshold=float(getattr(args, "grasp_dist_threshold", 0.03)),
        )


class GripperCalibrationPolicy(HeuristicServoLiftPolicy):
    """Calibration policy for measuring gripper closure limits.

    Two scenarios:
      - ``empty_close``: keep the end-effector at its initial pose and command
        the gripper to close.  Records the minimum open width achievable
        without any object between the fingers.
      - ``blocked_close``: servo above the object, descend to grasp height, and
        command the gripper to close.  Records the open width when the cube is
        between the fingers.

    The trace contains ``gripper_pos`` and ``close_command`` so the host can
    compare closure limits across command magnitudes.
    """

    name = "gripper_calibration"
    config_class = GripperCalibrationPolicyArgs

    def __init__(self, config: GripperCalibrationPolicyArgs):
        # Initialise PolicyBase directly so we can set our own state machine
        # without inheriting the full servo defaults from HeuristicServoLiftPolicy.
        PolicyBase.__init__(self, config)
        self._step = 0
        self._skill_hints = set()
        self._relative_mode: bool | None = None
        self._action_scale: float = 1.0
        self._episode_idx = 0

        self._scenario = config.scenario
        self._close_command = config.close_command
        self._close_steps = config.close_steps
        self._approach_offset_z = config.approach_offset_z
        self._grasp_offset_z = config.grasp_offset_z
        self._kp = config.kp
        self._grasp_dist_threshold = config.grasp_dist_threshold

        # For blocked_close we still use a small state machine.
        if self._scenario == "blocked_close":
            self._state = "APPROACH"
        else:
            self._state = "CLOSE"
        self._state_step = 0

        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        step = self._step
        self._step += 1
        self._state_step += 1

        if step == 0:
            import sys
            print(
                f"[GRIPPER_CALIBRATION] scenario={self._scenario} "
                f"close_command={self._close_command:.3f} close_steps={self._close_steps}",
                file=sys.stderr,
            )
            sys.stderr.flush()

        if self._relative_mode is None:
            self._infer_controller_mode(env)

        eef_pos, eef_quat, object_pos, gripper_pos, _target_pos = self._extract_state(
            observation, env, device
        )

        if self._state == "APPROACH":
            target = object_pos.clone() if object_pos is not None else eef_pos.clone()
            target[2] += self._approach_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            if object_pos is not None and eef_pos is not None:
                horiz = torch.norm(object_pos[:2] - eef_pos[:2])
                z_err = abs(eef_pos[2] - target[2])
                if horiz < 0.05 and z_err < self._approach_offset_z * 0.5:
                    self._transition("DESCEND")

        elif self._state == "DESCEND":
            target = object_pos.clone() if object_pos is not None else eef_pos.clone()
            target[2] += self._grasp_offset_z
            self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper(action, open=True)
            if object_pos is not None and eef_pos is not None:
                if torch.norm(target - eef_pos) < self._grasp_dist_threshold:
                    self._transition("CLOSE")

        elif self._state == "CLOSE":
            # Stay at the current commanded position; do not drag the arm while
            # measuring gripper closure.
            if self._scenario == "blocked_close" and object_pos is not None:
                target = object_pos.clone()
                target[2] += self._grasp_offset_z
                self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper_value(action, self._close_command)
            if self._state_step >= self._close_steps:
                self._transition("HOLD")

        elif self._state == "HOLD":
            if self._scenario == "blocked_close" and object_pos is not None:
                target = object_pos.clone()
                target[2] += self._grasp_offset_z
                self._apply_position(action, eef_pos, eef_quat, target)
            action = self._set_gripper_value(action, self._close_command)

        if object_pos is not None:
            _append_trace({
                "episode": self._episode_idx,
                "step": step,
                "eef_x": float(eef_pos[0].item()) if eef_pos is not None else None,
                "eef_y": float(eef_pos[1].item()) if eef_pos is not None else None,
                "eef_z": float(eef_pos[2].item()) if eef_pos is not None else None,
                "object_x": float(object_pos[0].item()),
                "object_y": float(object_pos[1].item()),
                "object_z": float(object_pos[2].item()),
                "gripper_pos": float(gripper_pos.item()) if gripper_pos is not None else None,
                "close_command": self._close_command,
                "action_norm": float(torch.linalg.norm(action).item()),
                "phase": self._state,
            })

        return action

    def _set_gripper_value(self, action: torch.Tensor, value: float) -> torch.Tensor:
        """Set the gripper command dimension to an arbitrary signed value."""
        if self._relative_mode and action.shape[-1] >= 7:
            action[..., 6] = value
        elif action.shape[-1] >= 8:
            action[..., -1] = value
        return action

    def _apply_position(
        self,
        action: torch.Tensor,
        eef_pos: torch.Tensor | None,
        eef_quat: torch.Tensor | None,
        target: torch.Tensor,
        kp_multiplier: float = 1.0,
        horizontal_scale: float = 1.0,
        max_delta: float | None = None,
    ) -> None:
        """Write a position command using body-frame relative mapping.

        The Franka relative controller is yawed ~180 deg at reset, so
        world-frame deltas must be rotated into the end-effector body frame.
        This mirrors the mapping used by ``HeuristicServoGoalPosePolicy``.
        """
        if eef_pos is None:
            return
        delta_world = self._kp * kp_multiplier * (target - eef_pos)
        if horizontal_scale != 1.0:
            delta_world[:2] *= horizontal_scale

        if max_delta is None:
            max_delta = 0.5 if self._relative_mode else 0.1
        delta_world = torch.clamp(delta_world, -max_delta, max_delta)

        if self._relative_mode:
            body_delta = self._world_delta_to_body(delta_world, eef_quat)
            cmd = body_delta / self._action_scale
            action[..., :3] = torch.clamp(cmd, -1.0, 1.0)
            if action.shape[-1] >= 6:
                action[..., 3:6] = 0.0
        else:
            action[..., :3] = eef_pos + delta_world
            if action.shape[-1] >= 7:
                quat = (
                    eef_quat
                    if eef_quat is not None and eef_quat.numel() >= 4
                    else torch.tensor([0.0, 0.0, 0.0, 1.0], device=action.device, dtype=action.dtype)
                )
                action[..., 3:7] = quat[:4]

    def _world_delta_to_body(
        self, delta_world: torch.Tensor, eef_quat: torch.Tensor | None
    ) -> torch.Tensor:
        """Rotate a world-frame delta into the end-effector body frame."""
        if eef_quat is None or eef_quat.numel() < 4:
            return delta_world
        try:
            from isaaclab.utils.math import quat_rotate_inverse

            return quat_rotate_inverse(eef_quat.unsqueeze(0), delta_world.unsqueeze(0)).squeeze()
        except Exception:
            return delta_world

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._state_step = 0
        self._episode_idx += 1
        if self._scenario == "blocked_close":
            self._state = "APPROACH"
        else:
            self._state = "CLOSE"

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "GripperCalibrationPolicy":
        return GripperCalibrationPolicy(GripperCalibrationPolicyArgs.from_cli_args(args))


@dataclass
class RotationalCalibrationPolicyArgs:
    """Configuration for rotational action calibration."""

    skill_hints: list[str] | None = None
    calibration_axis: int = 5  # 3=roll, 4=pitch, 5=yaw
    calibration_sign: float = 1.0
    calibration_magnitude: float = 0.5
    calibration_steps: int = 50
    use_quaternion_target: bool = False
    target_yaw_delta: float = 0.785398  # 45 degrees

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "RotationalCalibrationPolicyArgs":
        return cls(
            skill_hints=getattr(args, "skill_hints", None),
            calibration_axis=int(getattr(args, "calibration_axis", 5)),
            calibration_sign=float(getattr(args, "calibration_sign", 1.0)),
            calibration_magnitude=float(getattr(args, "calibration_magnitude", 0.5)),
            calibration_steps=int(getattr(args, "calibration_steps", 50)),
            use_quaternion_target=bool(getattr(args, "use_quaternion_target", False)),
            target_yaw_delta=float(getattr(args, "target_yaw_delta", 0.785398)),
        )


class RotationalCalibrationPolicy(PolicyBase):
    """Fixed rotational-action calibration policy.

    Commands a constant rotation on a single action axis and records the
    resulting end-effector roll/pitch/yaw.  Used to determine which
    action[3:6] axis maps to which world-frame rotation axis in relative mode.
    """

    name = "rotational_calibration"
    config_class = RotationalCalibrationPolicyArgs

    def __init__(self, config: RotationalCalibrationPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._axis = int(config.calibration_axis)
        self._sign = float(config.calibration_sign)
        self._magnitude = float(config.calibration_magnitude)
        self._calibration_steps = int(config.calibration_steps)
        self._use_quaternion_target = bool(config.use_quaternion_target)
        self._target_yaw_delta = float(config.target_yaw_delta)
        self._episode_idx = 0
        self._initial_quat: torch.Tensor | None = None
        self._target_quat: torch.Tensor | None = None
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        action_dim = int(action.shape[-1])

        # One-shot introspection of the action manager and controller config.
        if self._step == 0:
            self._introspect_action_manager(env)

        # Read current end-effector pose first; absolute mode needs it as the
        # position component of the command.
        eef_pos: torch.Tensor | None = None
        eef_quat: torch.Tensor | None = None
        try:
            scene = env.unwrapped.scene
            if "ee_frame" in scene.keys():
                data = scene["ee_frame"].data
                for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                    if hasattr(data, attr):
                        pos = getattr(data, attr).squeeze().to(device)
                        if pos.ndim > 1:
                            pos = pos[0]
                        if pos.numel() >= 3:
                            eef_pos = pos
                            break
                for attr in ("quat_w", "target_quat_w", "source_quat_w"):
                    if hasattr(data, attr):
                        quat = getattr(data, attr).squeeze().to(device)
                        if quat.ndim > 1:
                            quat = quat[0]
                        if quat.numel() >= 4:
                            eef_quat = quat
                            break
        except Exception:
            pass

        # Convert world-frame eef pose to the action term's base frame for
        # absolute-mode commands.  Prefer reading directly from the arm action
        # term because it already accounts for body_offset.
        eef_pos_b = eef_pos
        eef_quat_b = eef_quat
        try:
            am = env.unwrapped.action_manager
            arm_action = am.get_term("arm_action")
            if arm_action is not None and hasattr(arm_action, "_compute_frame_pose"):
                pose_b, quat_b = arm_action._compute_frame_pose()
                eef_pos_b = pose_b.squeeze().to(device)
                eef_quat_b = quat_b.squeeze().to(device)
                if eef_pos_b.ndim > 1:
                    eef_pos_b = eef_pos_b[0]
                if eef_quat_b.ndim > 1:
                    eef_quat_b = eef_quat_b[0]
        except Exception:
            pass

        # Capture initial orientation and compute target quaternion for the
        # absolute-quaternion calibration mode.
        if eef_quat_b is not None and self._initial_quat is None:
            self._initial_quat = eef_quat_b.clone()
            half = self._target_yaw_delta / 2.0
            # q = [x, y, z, w]; delta yaw about z
            delta_quat = torch.tensor(
                [0.0, 0.0, math.sin(half), math.cos(half)],
                dtype=eef_quat_b.dtype,
                device=device,
            )
            # target = initial * delta (Hamilton product, [x,y,z,w] order).
            ix, iy, iz, iw = (
                self._initial_quat[0],
                self._initial_quat[1],
                self._initial_quat[2],
                self._initial_quat[3],
            )
            dx, dy, dz, dw = delta_quat[0], delta_quat[1], delta_quat[2], delta_quat[3]
            tx = iw * dx + ix * dw + iy * dz - iz * dy
            ty = iw * dy - ix * dz + iy * dw + iz * dx
            tz = iw * dz + ix * dy - iy * dx + iz * dw
            tw = iw * dw - ix * dx - iy * dy - iz * dz
            self._target_quat = torch.tensor(
                [tx, ty, tz, tw], dtype=eef_quat_b.dtype, device=device
            )
            self._target_quat = self._target_quat / (torch.norm(self._target_quat) + 1e-8)

        active = self._step < self._calibration_steps
        if active:
            if self._use_quaternion_target:
                # Command a target pose as position + quaternion (in robot base frame).
                # 8-dim action: [pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w, gripper]
                if action_dim >= 8 and eef_pos_b is not None and self._target_quat is not None:
                    action[..., 0:3] = eef_pos_b[:3]
                    action[..., 3:7] = self._target_quat[:4]
                    action[..., 7] = 1.0  # gripper open
                elif action_dim >= 7:
                    # 7-dim action space cannot hold a full pose target + gripper.
                    pass
            else:
                action[..., self._axis] = self._sign * self._magnitude
                # Keep gripper open/neutral.
                if action_dim >= 7:
                    action[..., 6] = 1.0

        # Record eef pose and orientation.
        if eef_pos is not None and eef_quat is not None:
            roll, pitch, yaw = _quat_to_rpy(eef_quat)
            trace_record = {
                "episode": self._episode_idx,
                "step": self._step,
                "eef_x": float(eef_pos[0].item()),
                "eef_y": float(eef_pos[1].item()),
                "eef_z": float(eef_pos[2].item()),
                "eef_roll": roll,
                "eef_pitch": pitch,
                "eef_yaw": yaw,
                "action_dim": action_dim,
                "use_quaternion_target": self._use_quaternion_target,
                "action_axis": self._axis,
                "action_sign": self._sign,
                "action_magnitude": self._magnitude,
                "action_value": float(action[..., self._axis].item()) if active else 0.0,
                "action_norm": float(torch.linalg.norm(action).item()),
            }
            if self._target_quat is not None:
                trace_record["target_quat"] = [
                    float(self._target_quat[0].item()),
                    float(self._target_quat[1].item()),
                    float(self._target_quat[2].item()),
                    float(self._target_quat[3].item()),
                ]
            if eef_quat is not None:
                trace_record["eef_quat_world"] = [
                    float(eef_quat[0].item()),
                    float(eef_quat[1].item()),
                    float(eef_quat[2].item()),
                    float(eef_quat[3].item()),
                ]
            if eef_quat_b is not None:
                trace_record["eef_quat_base"] = [
                    float(eef_quat_b[0].item()),
                    float(eef_quat_b[1].item()),
                    float(eef_quat_b[2].item()),
                    float(eef_quat_b[3].item()),
                ]
            _append_trace(trace_record)

        self._step += 1
        return action

    def _introspect_action_manager(self, env: gym.Env) -> None:
        """Print action-manager and controller configuration for debugging.

        This is a one-shot diagnostic to understand why rotation commands do not
        produce end-effector rotation.
        """

        def _safe_lines(obj: Any, label: str, attrs: tuple[str, ...]) -> list[str]:
            lines: list[str] = [f"--- {label} ---"]
            if obj is None:
                lines.append("  None")
                return lines
            lines.append(f"  type: {type(obj).__name__}")
            for attr in attrs:
                try:
                    val = getattr(obj, attr, "<missing>")
                    lines.append(f"  {attr}: {val}")
                except Exception as exc:
                    lines.append(f"  {attr}: <error: {exc}>")
            return lines

        try:
            unwrapped = getattr(env, "unwrapped", env)
            lines: list[str] = []
            lines.append("=" * 60)
            lines.append("ROTATIONAL CALIBRATION INTROSPECTION")
            lines.append(f"action_space: {getattr(env, 'action_space', None)}")
            lines.append(f"device: {getattr(unwrapped, 'device', None)}")

            am = getattr(unwrapped, "action_manager", None)
            if am is not None:
                lines.append(f"action_manager: {type(am).__name__}")
                terms = list(getattr(am, "active_terms", []))
                lines.append(f"active_terms: {terms}")
                lines.append(f"_term_names: {list(getattr(am, '_term_names', []))}")
                lines.append(f"_terms keys: {list(getattr(am, '_terms', {}).keys())}")
                lines.append(f"total_action_dim: {getattr(am, 'total_action_dim', None)}")
                lines.append(f"action_term_dim: {getattr(am, 'action_term_dim', None)}")

                for term_name in terms:
                    # Try both attribute access and the get_term helper.
                    term = None
                    try:
                        term = am.get_term(term_name)
                    except Exception:
                        term = getattr(am, term_name, None)
                    lines.extend(_safe_lines(term, f"term {term_name}", ("cfg", "controller", "asset_name", "body_name", "joint_names", "command_type", "use_relative_mode", "ik_method", "scale")))
                    if term is not None:
                        cfg = getattr(term, "cfg", None)
                        lines.extend(_safe_lines(cfg, f"term {term_name} cfg", ("command_type", "use_relative_mode", "ik_method", "scale", "body_name", "asset_name", "joint_names", "body_offset", "action_name")))
                        controller = getattr(term, "controller", None)
                        lines.extend(_safe_lines(controller, f"term {term_name} controller", ("use_relative_mode", "ik_method", "command_type", "nullspace_mode", "solver_type", "command_dof", "asset_name", "body_name", "joint_names")))
            else:
                lines.append("action_manager: NOT FOUND")

            scene = getattr(unwrapped, "scene", None)
            if scene is not None and "ee_frame" in scene.keys():
                ee_data = scene["ee_frame"].data
                for attr in ("body_name", "offset", "parent_name"):
                    if hasattr(ee_data, attr):
                        lines.append(f"ee_frame.{attr}: {getattr(ee_data, attr)}")

            lines.append("=" * 60)
            msg = "\n".join(lines)
            print(msg, file=sys.stderr, flush=True)
            # Also append a single-line record to the trace for persistence.
            _append_trace({"introspection": msg})
        except Exception as exc:
            print(f"INTROSPECTION ERROR: {exc}", file=sys.stderr, flush=True)

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._episode_idx += 1

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "RotationalCalibrationPolicy":
        return RotationalCalibrationPolicy(RotationalCalibrationPolicyArgs.from_cli_args(args))


@dataclass
class JointSpaceCalibrationPolicyArgs:
    """Configuration for joint-space calibration of wrist yaw authority."""

    skill_hints: list[str] | None = None
    joint_index: int = 6  # 0-6 maps to panda_joint1..panda_joint7
    command_value: float = 0.4  # action-space command (target delta = scale * command)
    calibration_steps: int = 100
    gripper_open: bool = True

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "JointSpaceCalibrationPolicyArgs":
        return cls(
            skill_hints=getattr(args, "skill_hints", None),
            joint_index=int(getattr(args, "joint_index", 6)),
            command_value=float(getattr(args, "command_value", 0.4)),
            calibration_steps=int(getattr(args, "calibration_steps", 100)),
            gripper_open=bool(getattr(args, "gripper_open", True)),
        )


class JointSpaceCalibrationPolicy(PolicyBase):
    """Joint-space calibration policy for Franka joint-position control.

    Commands a fixed offset on a single arm joint (default panda_joint7 for
    wrist yaw) and records the resulting end-effector orientation change.  This
    tests whether joint-space control can produce end-effector rotation when
    task-space IK orientation control is broken.

    For ``franka_joint_pos`` the action space is 8-dimensional:
      action[0:7] → panda_joint1..panda_joint7 targets
      action[7]   → gripper command
    ``JointPositionActionCfg`` uses ``use_default_offset=True`` and ``scale=0.5``,
    so a commanded action value ``a`` on joint ``i`` drives that joint toward
    ``default_joint_pos[i] + 0.5 * a``.
    """

    name = "joint_space_calibration"
    config_class = JointSpaceCalibrationPolicyArgs

    # Default Franka arm joint positions from Arena's reset event.
    _DEFAULT_ARM_JOINTS: list[float] = [
        0.0, -0.785, -0.1107, -1.1775, 0.0, 0.785, 0.785
    ]

    def __init__(self, config: JointSpaceCalibrationPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._joint_index = int(config.joint_index)
        self._command_value = float(config.command_value)
        self._calibration_steps = int(config.calibration_steps)
        self._gripper_open = bool(config.gripper_open)
        self._episode_idx = 0
        self._initial_quat: torch.Tensor | None = None
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        device = torch.device(env.unwrapped.device)
        action = torch.zeros(env.action_space.shape, device=device)
        action_dim = int(action.shape[-1])

        # Read current end-effector pose and joint positions.
        eef_pos: torch.Tensor | None = None
        eef_quat: torch.Tensor | None = None
        joint_pos: torch.Tensor | None = None
        try:
            scene = env.unwrapped.scene
            if "ee_frame" in scene.keys():
                data = scene["ee_frame"].data
                for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                    if hasattr(data, attr):
                        pos = getattr(data, attr).squeeze().to(device)
                        if pos.ndim > 1:
                            pos = pos[0]
                        if pos.numel() >= 3:
                            eef_pos = pos
                            break
                for attr in ("quat_w", "target_quat_w", "source_quat_w"):
                    if hasattr(data, attr):
                        quat = getattr(data, attr).squeeze().to(device)
                        if quat.ndim > 1:
                            quat = quat[0]
                        if quat.numel() >= 4:
                            eef_quat = quat
                            break
            if "robot" in scene.keys():
                robot_data = scene["robot"].data
                if hasattr(robot_data, "joint_pos"):
                    joints = robot_data.joint_pos.squeeze().to(device)
                    if joints.ndim > 1:
                        joints = joints[0]
                    if joints.numel() >= 7:
                        joint_pos = joints[:7]
        except Exception:
            pass

        if eef_quat is not None and self._initial_quat is None:
            self._initial_quat = eef_quat.clone()

        active = self._step < self._calibration_steps
        if active and 0 <= self._joint_index < 7 and action_dim >= 7:
            # Command a fixed action value. With scale=0.5 and default offset,
            # the joint will servo toward default + 0.5 * command_value.
            action[..., self._joint_index] = self._command_value

        # Gripper command is the last dimension.
        if action_dim >= 8:
            action[..., 7] = 1.0 if self._gripper_open else -1.0

        # Record trace.
        if eef_pos is not None and eef_quat is not None:
            roll, pitch, yaw = _quat_to_rpy(eef_quat)
            trace_record: dict[str, Any] = {
                "episode": self._episode_idx,
                "step": self._step,
                "eef_x": float(eef_pos[0].item()),
                "eef_y": float(eef_pos[1].item()),
                "eef_z": float(eef_pos[2].item()),
                "eef_roll": roll,
                "eef_pitch": pitch,
                "eef_yaw": yaw,
                "action_dim": action_dim,
                "joint_index": self._joint_index,
                "command_value": self._command_value,
                "action_norm": float(torch.linalg.norm(action).item()),
            }
            if joint_pos is not None:
                trace_record["joint_pos"] = [float(j.item()) for j in joint_pos]
            if self._initial_quat is not None:
                trace_record["initial_eef_quat"] = [
                    float(self._initial_quat[i].item()) for i in range(4)
                ]
            _append_trace(trace_record)

        self._step += 1
        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._episode_idx += 1
        self._initial_quat = None

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "JointSpaceCalibrationPolicy":
        return JointSpaceCalibrationPolicy(JointSpaceCalibrationPolicyArgs.from_cli_args(args))
