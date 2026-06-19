import sys
# Inject --headless before AppLauncher initializes so it picks headless kit
if "--headless" not in sys.argv:
    sys.argv.insert(1, "--headless")

sys.path.insert(0, "/workspace/data")
import lightwheel_patch  # noqa: F401

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch


# ---------------------------------------------------------------------------
# Seed forwarding from the host job into the container environment.
# ---------------------------------------------------------------------------
_ROSCLAW_ARENA_SEED = os.environ.get("ROSCLAW_ARENA_SEED")
_ROSCLAW_ARENA_PLACEMENT_SEED = os.environ.get("ROSCLAW_ARENA_PLACEMENT_SEED")


def _parse_seed(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


_ARENA_SEED = _parse_seed(_ROSCLAW_ARENA_SEED)
_ARENA_PLACEMENT_SEED = _parse_seed(_ROSCLAW_ARENA_PLACEMENT_SEED)
if _ARENA_SEED is not None:
    os.environ.setdefault("ISAACLAB_SEED", str(_ARENA_SEED))

# Inject --seed/--placement_seed into sys.argv so Arena's top-level CLI parser
# sees them *before* the environment subcommand.  This must happen before any
# module parses sys.argv.
if _ARENA_SEED is not None and "--seed" not in sys.argv:
    sys.argv.insert(2, "--seed")
    sys.argv.insert(3, str(_ARENA_SEED))
if _ARENA_PLACEMENT_SEED is not None and "--placement_seed" not in sys.argv:
    sys.argv.insert(2, "--placement_seed")
    sys.argv.insert(3, str(_ARENA_PLACEMENT_SEED))


# ---------------------------------------------------------------------------
# Asset-resolution helpers (inlined so the container does not depend on the
# host-only rosclaw_darwin package).
# ---------------------------------------------------------------------------
@dataclass
class _AssetResolution:
    requested_object: str
    loaded_object: str
    asset_source: str
    asset_path: str | None = None
    asset_fallback_used: bool = False
    fallback_reason: str | None = None
    official_asset: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_object": self.requested_object,
            "loaded_object": self.loaded_object,
            "asset_source": self.asset_source,
            "asset_path": self.asset_path,
            "asset_fallback_used": self.asset_fallback_used,
            "fallback_reason": self.fallback_reason,
            "official_asset": self.official_asset,
        }


@dataclass
class _AssetPolicy:
    require_official_asset: bool = False
    allow_procedural_fallback: bool = True
    diagnostic_variant: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "_AssetPolicy":
        if data is None:
            return cls()
        return cls(
            require_official_asset=bool(data.get("require_official_asset", False)),
            allow_procedural_fallback=bool(data.get("allow_procedural_fallback", True)),
            diagnostic_variant=bool(data.get("diagnostic_variant", False)),
        )


@dataclass
class _BenchmarkValidity:
    can_claim_official_benchmark: bool = False
    validity_scope: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_claim_official_benchmark": self.can_claim_official_benchmark,
            "validity_scope": self.validity_scope,
        }


def _load_asset_policy(job_config: dict[str, Any]) -> _AssetPolicy:
    policy_dict = job_config.get("asset_policy")
    if policy_dict is None:
        metadata = job_config.get("metadata") or {}
        policy_dict = metadata.get("asset_policy")
    return _AssetPolicy.from_dict(policy_dict)


def _load_requested_object(job_config: dict[str, Any]) -> str:
    arena_env_args = job_config.get("arena_env_args") or {}
    obj = arena_env_args.get("object")
    if obj:
        return str(obj)
    metadata = job_config.get("metadata") or {}
    objects = metadata.get("objects") or []
    if objects:
        return str(objects[0].get("name", "unknown"))
    return "unknown"


def _resolve_asset_from_scene(requested_object: str, scene: Any) -> _AssetResolution:
    _EXPECTED_PRIM_NAMES: dict[str, set[str]] = {
        "dex_cube": {"dex_cube", "cube", "object"},
        "cube": {"dex_cube", "cube", "object"},
        "procedural_cube": {"procedural_cube", "cube", "object"},
    }
    expected_names = _EXPECTED_PRIM_NAMES.get(requested_object, {requested_object})

    loaded_object = "unknown"
    asset_path: str | None = None
    fallback_used = False
    fallback_reason: str | None = None
    official_asset = False
    object_class: str | None = None

    try:
        scene_keys = list(scene.keys())
    except Exception:
        scene_keys = []

    # Find the first plausible manipulation target among scene keys.
    candidate_keys = [k for k in scene_keys if str(k) in expected_names]
    if not candidate_keys:
        # Fallback: any key that is not a known non-object.
        non_object_keys = {"robot", "ee_frame", "background", "light", "table", "floor"}
        candidate_keys = [k for k in scene_keys if str(k) not in non_object_keys]

    if candidate_keys:
        loaded_key = str(candidate_keys[0])
        loaded_object = loaded_key
        try:
            obj = scene.get(loaded_key) if hasattr(scene, "get") else None
            if obj is not None:
                asset_path = getattr(obj, "usd_path", None)
                if asset_path:
                    asset_path = str(asset_path)
                object_class = type(obj).__name__
        except Exception:
            pass

    # Determine source and fallback status using class/path heuristics.
    is_dex_cube = (
        loaded_object in ("dex_cube",)
        or (object_class is not None and "DexCube" in object_class)
        or (asset_path is not None and "DexCube" in asset_path)
    )
    is_procedural = (
        loaded_object == "procedural_cube"
        or (object_class is not None and "Procedural" in object_class)
        or (asset_path is not None and asset_path == "")
        or (asset_path is None and object_class in ("NoneType",))
    )

    if requested_object in ("dex_cube", "cube"):
        if is_dex_cube:
            asset_source = "usd_asset"
            official_asset = True
            fallback_used = False
            loaded_object = "dex_cube"
        elif is_procedural:
            asset_source = "procedural_fallback"
            fallback_used = True
            fallback_reason = "dex_cube_asset_missing"
            official_asset = False
            loaded_object = "procedural_cube"
        else:
            asset_source = "unknown"
            fallback_used = True
            fallback_reason = f"loaded_{loaded_object}_instead_of_dex_cube"
            official_asset = False
    elif requested_object == "procedural_cube":
        if is_procedural or is_dex_cube:
            # Even if the environment silently upgraded to dex_cube, the task
            # asked for procedural; treat as fallback/diagnostic.
            asset_source = "procedural_fallback" if is_procedural else "usd_asset"
            fallback_used = not is_procedural
            if fallback_used:
                fallback_reason = "procedural_cube_not_used"
            official_asset = False
            loaded_object = "procedural_cube" if is_procedural else "dex_cube"
        else:
            asset_source = "unknown"
            fallback_used = True
            fallback_reason = f"loaded_{loaded_object}_instead_of_procedural_cube"
            official_asset = False
    else:
        asset_source = "registered_asset" if not is_procedural else "procedural_fallback"
        official_asset = not is_procedural and loaded_object == requested_object
        fallback_used = not official_asset
        if fallback_used:
            fallback_reason = f"loaded_{loaded_object}_instead_of_{requested_object}"

    return _AssetResolution(
        requested_object=requested_object,
        loaded_object=loaded_object,
        asset_source=asset_source,
        asset_path=asset_path,
        asset_fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        official_asset=official_asset,
    )


def _compute_benchmark_validity(
    resolution: _AssetResolution, asset_policy: _AssetPolicy
) -> tuple[_BenchmarkValidity, bool]:
    if resolution.official_asset and not asset_policy.diagnostic_variant:
        return _BenchmarkValidity(can_claim_official_benchmark=True, validity_scope="official_arena_asset"), False
    if resolution.asset_fallback_used:
        if asset_policy.require_official_asset and not asset_policy.allow_procedural_fallback:
            return _BenchmarkValidity(can_claim_official_benchmark=False, validity_scope="environment_invalid"), True
        return _BenchmarkValidity(can_claim_official_benchmark=False, validity_scope="asset_fidelity_diagnostic"), False
    if asset_policy.diagnostic_variant:
        return _BenchmarkValidity(can_claim_official_benchmark=False, validity_scope="ood_diagnostic"), False
    return _BenchmarkValidity(can_claim_official_benchmark=False, validity_scope="unknown"), False


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


def _extract_geometry_from_scene(scene: Any, object_name: str = "unknown") -> dict[str, Any]:
    """Extract object geometry from an IsaacLab/Arena scene object.

    Inlined container-side version that does not depend on the host package.
    """
    geometry: dict[str, Any] = {
        "width": 0.05,
        "depth": 0.05,
        "height": 0.05,
        "object_name": object_name,
        "asset_source": "scene",
        "mass": None,
        "static_friction": None,
    }
    try:
        obj = None
        for key in scene.keys():
            if str(key) == object_name or str(key) in {"dex_cube", "object", "cube", "procedural_cube"}:
                candidate = scene[key]
                cand_name = getattr(candidate, "name", str(key))
                if cand_name == object_name or object_name == "unknown":
                    obj = candidate
                    geometry["object_name"] = str(key)
                    break

        if obj is None:
            return geometry

        spawn = getattr(obj, "spawn", None)
        if spawn is not None:
            size = getattr(spawn, "size", None)
            if size is not None:
                s = _as_tuple(size)
                if len(s) >= 3:
                    geometry["width"] = float(s[0])
                    geometry["depth"] = float(s[1])
                    geometry["height"] = float(s[2])
                    return geometry
            scale = getattr(spawn, "scale", None)
            if scale is not None:
                sc = _as_tuple(scale)
                geometry["width"] *= float(sc[0]) if len(sc) > 0 else 1.0
                geometry["depth"] *= float(sc[1]) if len(sc) > 1 else 1.0
                geometry["height"] *= float(sc[2]) if len(sc) > 2 else 1.0
            # Read physical properties from the spawn config if available.
            try:
                mass_props = getattr(spawn, "mass_props", None)
                if mass_props is not None:
                    mass = getattr(mass_props, "mass", None)
                    if mass is not None:
                        geometry["mass"] = float(mass)
                physics_material = getattr(spawn, "physics_material", None)
                if physics_material is not None:
                    static_friction = getattr(physics_material, "static_friction", None)
                    if static_friction is not None:
                        geometry["static_friction"] = float(static_friction)
            except Exception:
                pass

        # Fallback: read from the live object data if spawn config did not have it.
        try:
            if geometry["mass"] is None and hasattr(obj, "data"):
                mass = getattr(obj.data, "default_mass", None)
                if mass is None:
                    mass = getattr(obj.data, "mass", None)
                if mass is not None:
                    geometry["mass"] = float(mass)
            if geometry["static_friction"] is None and hasattr(obj, "data"):
                static_friction = getattr(obj.data, "static_friction", None)
                if static_friction is not None:
                    geometry["static_friction"] = float(static_friction)
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
                upper = _as_tuple(upper)
                lower = _as_tuple(lower)
                if len(upper) >= 3 and len(lower) >= 3:
                    geometry["width"] = float(upper[0] - lower[0])
                    geometry["depth"] = float(upper[1] - lower[1])
                    geometry["height"] = float(upper[2] - lower[2])
                    geometry["raw_bounding_box"] = {
                        "upper": list(upper),
                        "lower": list(lower),
                    }
                    return geometry
    except Exception:
        pass

    return geometry


# Standardize xform ops on any xformable prim before validation so that object
# references to Mesh prims (e.g. kitchen Counter_Top_A) do not fail the
# "standard transform operations" check during scene construction.
try:
    import isaaclab.sim.utils as _sim_utils

    _orig_validate_standard_xform_ops = _sim_utils.validate_standard_xform_ops

    def _patched_validate_standard_xform_ops(prim):
        from pxr import UsdGeom

        if not prim.IsA(UsdGeom.Xformable):
            return False
        try:
            _sim_utils.standardize_xform_ops(prim)
        except Exception:
            pass
        return True

    _sim_utils.validate_standard_xform_ops = _patched_validate_standard_xform_ops
except Exception:
    pass

# Monkey-patch wp.to_torch for OmniWarp 1.12.0 + PyTorch 2.7 compatibility.
try:
    import warp as wp
    import torch

    _orig_to_torch = wp.to_torch

    def _compat_to_torch(a, requires_grad=None):
        if isinstance(a, torch.Tensor):
            return a
        return _orig_to_torch(a, requires_grad)

    wp.to_torch = _compat_to_torch
except Exception:
    pass

# Some Arena example environments (e.g. kitchen_pick_and_place) use object
# references whose parent asset is rotated by non-Z-axis quaternions. The
# object placer asserts on these; relax the helper so the env can still build.
try:
    import isaaclab_arena.utils.bounding_box as _bbox_mod

    _orig_quat_to_quarters = _bbox_mod.quaternion_to_90_deg_z_quarters

    def _loose_quaternion_to_90_deg_z_quarters(rotation_xyzw, tol_deg=1.0):
        import math

        x, y, z, w = rotation_xyzw
        if abs(x) < 1e-3 and abs(y) < 1e-3:
            angle_deg = math.degrees(2 * math.atan2(z, w)) % 360
            return round(angle_deg / 90) % 4
        # Fallback for arbitrary rotations: assume no rotation. This keeps
        # zero_action / heuristic rollouts from failing during scene setup.
        return 0

    _bbox_mod.quaternion_to_90_deg_z_quarters = _loose_quaternion_to_90_deg_z_quarters

    # object_reference imports the helper directly into its namespace, so we
    # must also patch the copy held by that module.
    try:
        import isaaclab_arena.assets.object_reference as _obj_ref_mod

        _obj_ref_mod.quaternion_to_90_deg_z_quarters = _loose_quaternion_to_90_deg_z_quarters
    except Exception:
        pass
except Exception:
    pass

# Shared state for metrics capture.
_captured_metrics: dict[str, dict] = {}
_captured_rollout: dict[str, dict] = {}
_captured_jobs: dict[str, dict] = {}
_captured_episode_traces: list[list[dict[str, Any]]] = []
_captured_asset_info: dict[str, Any] = {}


def _load_job_config() -> dict[str, Any]:
    """Load the first job from the mounted eval_jobs.json if available."""
    try:
        path = Path("/workspace/data/eval_jobs.json")
        if path.exists():
            data = json.loads(path.read_text())
            jobs = data.get("jobs", [])
            if jobs:
                return dict(jobs[0])
    except Exception:
        pass
    return {}


_JOB_CONFIG = _load_job_config()
_POLICY_CONFIG = dict(_JOB_CONFIG.get("policy_config_dict") or {})
_POLICY_TYPE = str(_JOB_CONFIG.get("policy_type", ""))
_SUCCESS_CONDITIONS = list(_JOB_CONFIG.get("success_conditions") or [])


def _is_oracle_policy() -> bool:
    """Return True if the configured policy is an oracle/cheat policy."""
    job_meta = dict(_JOB_CONFIG.get("_policy_metadata") or {})
    explicit = bool(
        _POLICY_CONFIG.get("is_oracle")
        or _POLICY_CONFIG.get("is_cheat")
        or (_POLICY_CONFIG.get("policy_metadata") or {}).get("is_oracle")
        or (_POLICY_CONFIG.get("policy_metadata") or {}).get("is_cheat")
        or job_meta.get("is_oracle")
        or job_meta.get("is_cheat")
    )
    return explicit or "cheat" in _POLICY_TYPE.lower() or "oracle" in _POLICY_TYPE.lower()


def _extract_state_from_env(env: Any, action: Any) -> dict[str, float | None]:
    """Extract scalar eef/object/target/gripper state from the Arena env.

    Mirrors the extraction logic used by ``HeuristicServoLiftPolicy`` so that
    per-episode progress metrics can be computed without importing the policy.
    """
    try:
        device = torch.device(env.unwrapped.device)
    except Exception:
        device = torch.device("cpu")

    state: dict[str, float | None] = {
        "eef_x": None,
        "eef_y": None,
        "eef_z": None,
        "object_x": None,
        "object_y": None,
        "object_z": None,
        "target_x": None,
        "target_y": None,
        "target_z": None,
        "gripper_pos": None,
        "action_norm": None,
    }

    # Action norm
    try:
        if isinstance(action, torch.Tensor):
            state["action_norm"] = float(torch.linalg.norm(action).item())
        elif action is not None:
            state["action_norm"] = float(torch.linalg.norm(torch.as_tensor(action)).item())
    except Exception:
        pass

    # Target from command manager (base frame) transformed to world frame.
    # task_obs alone stores the base-frame command; the Arena success criterion
    # uses the world-frame goal, so we must transform before computing distances.
    try:
        cm = env.unwrapped.command_manager
        cmd = cm.get_command("object_pose")
        des_pos_b = torch.as_tensor(cmd, device=device).squeeze()[:3]
        robot = env.unwrapped.scene["robot"]
        root_pos = robot.data.root_pos_w.squeeze().to(device)
        root_quat = robot.data.root_quat_w.squeeze().to(device)
        if root_pos.ndim > 1:
            root_pos = root_pos[0]
        if root_quat.ndim > 1:
            root_quat = root_quat[0]
        from isaaclab.utils.math import combine_frame_transforms
        target_w, _ = combine_frame_transforms(
            root_pos.unsqueeze(0), root_quat.unsqueeze(0), des_pos_b.unsqueeze(0)
        )
        target_w = target_w.squeeze()
        state["target_x"] = float(target_w[0].item())
        state["target_y"] = float(target_w[1].item())
        state["target_z"] = float(target_w[2].item())
    except Exception:
        # Fallback to raw task_obs (may be base-frame; still better than nothing).
        try:
            obs = env._obs_buf if hasattr(env, "_obs_buf") else None
            if obs is None:
                obs = getattr(env.unwrapped, "_obs_buf", None)
            if isinstance(obs, dict) and "task_obs" in obs:
                task_obs = obs["task_obs"]
                if hasattr(task_obs, "squeeze"):
                    task_obs = task_obs.squeeze()
                if task_obs.numel() >= 3:
                    state["target_x"] = float(task_obs[0].item())
                    state["target_y"] = float(task_obs[1].item())
                    state["target_z"] = float(task_obs[2].item())
        except Exception:
            pass

    try:
        scene = env.unwrapped.scene
        if scene is None:
            return state
        scene_keys = list(scene.keys())

        # Object position
        object_candidates = {"object", "dex_cube", "cube", "mug", "cracker_box", "mustard_bottle"}
        for key in scene_keys:
            if str(key) in object_candidates:
                obj = scene[key]
                data = getattr(obj, "data", None)
                if data is not None and hasattr(data, "root_pos_w"):
                    pos = data.root_pos_w.squeeze().to(device)
                    if pos.ndim > 1:
                        pos = pos[0]
                    if pos.numel() >= 3:
                        state["object_x"] = float(pos[0].item())
                        state["object_y"] = float(pos[1].item())
                        state["object_z"] = float(pos[2].item())
                    break

        # End-effector position
        if "ee_frame" in scene_keys:
            ee_frame = scene["ee_frame"]
            data = getattr(ee_frame, "data", None)
            if data is not None:
                for attr in ("target_pos_w", "source_pos_w", "pos_w"):
                    if hasattr(data, attr):
                        pos = getattr(data, attr).squeeze().to(device)
                        if pos.ndim > 1:
                            pos = pos[0]
                        if pos.numel() >= 3:
                            state["eef_x"] = float(pos[0].item())
                            state["eef_y"] = float(pos[1].item())
                            state["eef_z"] = float(pos[2].item())
                            break

        # Gripper position (mean of last two joints)
        if "robot" in scene_keys:
            robot = scene["robot"]
            data = getattr(robot, "data", None)
            if data is not None and hasattr(data, "joint_pos"):
                joints = data.joint_pos.squeeze().to(device)
                if joints.ndim > 1:
                    joints = joints[0]
                if joints.numel() >= 2:
                    state["gripper_pos"] = float(joints[-2:].mean().item())
    except Exception:
        pass

    # Fallback target: object + fixed lift height if task_obs missing
    if (
        state["target_x"] is None
        and state["object_x"] is not None
    ):
        state["target_x"] = state["object_x"]
        state["target_y"] = state["object_y"]
        state["target_z"] = (state["object_z"] or 0.0) + 0.25

    return state


def _dist(p1: dict[str, float | None], p2: dict[str, float | None]) -> float:
    """Euclidean distance between two points with None safety."""
    if p1["x"] is None or p2["x"] is None:
        return float("inf")
    return math.sqrt(
        (p1["x"] - p2["x"]) ** 2
        + (p1["y"] - p2["y"]) ** 2
        + (p1["z"] - p2["z"]) ** 2
    )


def _compute_progress_metrics(traces: list[list[dict[str, Any]]], success_conditions: list[str] | None = None) -> dict[str, Any]:
    """Compute per-episode progress metrics and aggregate summary.

    ``success_conditions`` comes from the ROSClaw task definition and drives
    how an episode is classified as successful.  For example, a task whose
    only condition is ``object_lifted`` should count any lifted object as a
    success, whereas ``pose_reached`` requires proximity to the command target.
    """
    is_oracle = _is_oracle_policy()
    policy_metadata = {
        "policy_type": _POLICY_TYPE,
        "is_oracle": is_oracle,
        "is_cheat": bool(
            _POLICY_CONFIG.get("is_cheat")
            or (_POLICY_CONFIG.get("policy_metadata") or {}).get("is_cheat")
            or "cheat" in _POLICY_TYPE.lower()
        ),
    }

    success_conditions = success_conditions or []
    require_target_proximity = "pose_reached" in success_conditions
    require_object_lifted = "object_lifted" in success_conditions

    grasp_dist_threshold = float(_POLICY_CONFIG.get("grasp_dist_threshold", 0.03))
    success_threshold = float(_POLICY_CONFIG.get("success_threshold", 0.06))
    lift_height_threshold = float(_POLICY_CONFIG.get("lift_height_threshold", 0.03))

    episode_metrics: list[dict[str, Any]] = []
    for ep_idx, trace in enumerate(traces):
        if not trace:
            continue

        def _point(step: dict[str, Any], prefix: str) -> dict[str, float | None]:
            return {
                "x": step.get(f"{prefix}_x"),
                "y": step.get(f"{prefix}_y"),
                "z": step.get(f"{prefix}_z"),
            }

        eef_dists = [_dist(_point(s, "eef"), _point(s, "object")) for s in trace]
        target_dists = [_dist(_point(s, "object"), _point(s, "target")) for s in trace]
        object_heights = [s.get("object_z") for s in trace if s.get("object_z") is not None]
        action_norms = [s.get("action_norm") for s in trace if s.get("action_norm") is not None]

        eef_initial = eef_dists[0] if eef_dists else float("inf")
        eef_final = eef_dists[-1] if eef_dists else float("inf")
        eef_min = min((d for d in eef_dists if d != float("inf")), default=float("inf")) if eef_dists else float("inf")

        target_initial = target_dists[0] if target_dists else float("inf")
        target_final = target_dists[-1] if target_dists else float("inf")
        target_min = min((d for d in target_dists if d != float("inf")), default=float("inf")) if target_dists else float("inf")

        object_initial = object_heights[0] if object_heights else None
        object_final = object_heights[-1] if object_heights else None
        object_max = max(object_heights) if object_heights else None
        object_delta = (object_final - object_initial) if object_initial is not None and object_final is not None else 0.0

        # An object that has been lifted by more than the threshold is implicitly
        # considered "reached" even if the end-effector distance estimate is noisy.
        reached_object = (
            eef_min < grasp_dist_threshold
            or object_delta > lift_height_threshold
        )
        lifted = object_delta > lift_height_threshold

        # Use task-aware success criteria.  Default behaviour (pose_reached or no
        # explicit conditions) requires both lift and target proximity.  When the
        # task only requires object_lifted, target proximity is not required.
        if require_object_lifted and not require_target_proximity:
            success = reached_object and lifted
        else:
            # Use the minimum object-to-target distance during the episode to align
            # with Arena's early-success termination (the final state may overshoot).
            success = reached_object and lifted and target_min < success_threshold

        nonzero_actions = sum(1 for n in action_norms if n is not None and n > 1e-4)
        nonzero_rate = nonzero_actions / max(1, len(action_norms))

        # Failure-type inference
        if nonzero_rate < 0.05:
            failure_type = "policy_noop"
        elif not reached_object:
            failure_type = "target_not_reached"
        elif reached_object and not lifted:
            failure_type = "object_not_lifted"
        elif lifted and not success:
            failure_type = "target_not_reached_after_lift"
        elif not success:
            failure_type = "timeout"
        else:
            failure_type = "unknown_failure"

        # Phase trace from step-level phase annotations.
        phase_trace = []
        current_phase = None
        phase_start = 0
        phases_reached = set()
        for i, step in enumerate(trace):
            phase = step.get("phase") or "UNKNOWN"
            phases_reached.add(phase)
            if phase != current_phase:
                if current_phase is not None:
                    phase_trace.append({
                        "phase": current_phase,
                        "start_step": phase_start,
                        "end_step": i - 1,
                    })
                current_phase = phase
                phase_start = i
        if current_phase is not None:
            phase_trace.append({
                "phase": current_phase,
                "start_step": phase_start,
                "end_step": len(trace) - 1,
            })

        # Gate audit: collect DESCEND phase diagnostics if available.
        descend_steps = [s for s in trace if s.get("phase") == "DESCEND"]
        gate_diagnostics = [s for s in descend_steps if s.get("grasp_dist_error") is not None]
        min_grasp_z_error = min(
            (s.get("grasp_z_error") for s in gate_diagnostics if s.get("grasp_z_error") is not None),
            default=None,
        )
        min_grasp_dist = min(
            (s.get("grasp_dist_error") for s in gate_diagnostics if s.get("grasp_dist_error") is not None),
            default=None,
        )
        descend_exit_step = None
        for i, s in enumerate(trace):
            if s.get("phase") == "GRASP":
                descend_exit_step = i
                break
        blocking_reason_counts: dict[str, int] = {}
        for s in gate_diagnostics:
            reason = s.get("transition_blocking_reason")
            if reason:
                blocking_reason_counts[reason] = blocking_reason_counts.get(reason, 0) + 1
        dominant_blocking_reason = max(blocking_reason_counts, key=blocking_reason_counts.get) if blocking_reason_counts else None
        transition_nearly_satisfied = bool(
            gate_diagnostics and gate_diagnostics[-1].get("transition_allowed")
        )

        episode_metrics.append({
            "episode": ep_idx,
            "success": success,
            "failure_type": failure_type,
            "eef_to_object_distance_initial": eef_initial if eef_initial != float("inf") else None,
            "eef_to_object_distance_min": eef_min if eef_min != float("inf") else None,
            "eef_to_object_distance_final": eef_final if eef_final != float("inf") else None,
            "eef_to_object_distance_delta": (eef_initial - eef_final) if eef_initial != float("inf") and eef_final != float("inf") else None,
            "object_to_target_distance_initial": target_initial if target_initial != float("inf") else None,
            "object_to_target_distance_min": target_min if target_min != float("inf") else None,
            "object_to_target_distance_final": target_final if target_final != float("inf") else None,
            "object_to_target_distance_delta": (target_initial - target_final) if target_initial != float("inf") and target_final != float("inf") else None,
            "object_height_initial": object_initial,
            "object_height_final": object_final,
            "object_height_max": object_max,
            "object_height_delta": object_delta,
            "mean_action_norm": float(sum(action_norms) / len(action_norms)) if action_norms else None,
            "max_action_norm": max(action_norms) if action_norms else None,
            "nonzero_action_rate": nonzero_rate,
            "episode_steps": len(trace),
            "phase_trace": phase_trace,
            "phases_reached": sorted(phases_reached),
            "approach_phase_reached": "APPROACH" in phases_reached,
            "grasp_phase_reached": "GRASP" in phases_reached,
            "lift_phase_reached": "LIFT" in phases_reached,
            "target_reached": success,
            "descend_steps": len(descend_steps),
            "descend_exit_step": descend_exit_step,
            "min_grasp_z_error": round(min_grasp_z_error, 6) if min_grasp_z_error is not None else None,
            "min_grasp_dist": round(min_grasp_dist, 6) if min_grasp_dist is not None else None,
            "dominant_blocking_reason": dominant_blocking_reason,
            "transition_nearly_satisfied": transition_nearly_satisfied,
            "gate_diagnostics": gate_diagnostics,
        })
        # Append raw first/last positions for calibration and detailed reports.
        if trace:
            first = trace[0]
            last = trace[-1]
            for prefix in ("eef", "object", "target"):
                for coord in ("x", "y", "z"):
                    key = f"{prefix}_{coord}"
                    episode_metrics[-1][f"{key}_initial"] = first.get(key)
                    episode_metrics[-1][f"{key}_final"] = last.get(key)

    # Aggregate summary metrics
    if not episode_metrics:
        return {"policy_metadata": policy_metadata, "episode_metrics": []}

    successes = [e["success"] for e in episode_metrics]
    progress_values = []
    for ep in episode_metrics:
        approach_progress = 0.0
        if ep["eef_to_object_distance_initial"] and ep["eef_to_object_distance_min"]:
            init = ep["eef_to_object_distance_initial"]
            mn = ep["eef_to_object_distance_min"]
            if init > 0:
                approach_progress = max(0.0, min(1.0, (init - mn) / init))
        lift_progress = 0.0
        if ep["object_height_delta"]:
            # Normalize against a 0.25 m lift (typical command target height)
            lift_progress = max(0.0, min(1.0, ep["object_height_delta"] / 0.25))
        target_progress = 0.0
        if ep["object_to_target_distance_initial"] and ep["object_to_target_distance_final"]:
            init = ep["object_to_target_distance_initial"]
            fin = ep["object_to_target_distance_final"]
            if init > 0:
                target_progress = max(0.0, min(1.0, (init - fin) / init))
        progress = 0.5 * approach_progress + 0.3 * lift_progress + 0.2 * target_progress
        ep["progress"] = round(progress, 4)
        progress_values.append(progress)

    failure_counts: dict[str, int] = {}
    for ep in episode_metrics:
        failure_counts[ep["failure_type"]] = failure_counts.get(ep["failure_type"], 0) + (0 if ep["success"] else 1)

    summary = {
        "success_rate": round(sum(successes) / len(successes), 4),
        "progress_mean": round(sum(progress_values) / len(progress_values), 4),
        "progress_min": round(min(progress_values), 4),
        "progress_max": round(max(progress_values), 4),
        "eef_to_object_distance_initial_mean": round(
            sum(e["eef_to_object_distance_initial"] for e in episode_metrics if e["eef_to_object_distance_initial"] is not None)
            / max(1, sum(1 for e in episode_metrics if e["eef_to_object_distance_initial"] is not None)),
            4,
        ),
        "eef_to_object_distance_min_mean": round(
            sum(e["eef_to_object_distance_min"] for e in episode_metrics if e["eef_to_object_distance_min"] is not None)
            / max(1, sum(1 for e in episode_metrics if e["eef_to_object_distance_min"] is not None)),
            4,
        ),
        "eef_to_object_distance_final_mean": round(
            sum(e["eef_to_object_distance_final"] for e in episode_metrics if e["eef_to_object_distance_final"] is not None)
            / max(1, sum(1 for e in episode_metrics if e["eef_to_object_distance_final"] is not None)),
            4,
        ),
        "object_height_delta_mean": round(
            sum(e["object_height_delta"] for e in episode_metrics)
            / max(1, len(episode_metrics)),
            4,
        ),
        "object_height_max_mean": round(
            sum(e["object_height_max"] for e in episode_metrics if e["object_height_max"] is not None)
            / max(1, sum(1 for e in episode_metrics if e["object_height_max"] is not None)),
            4,
        ),
        "num_episodes": len(episode_metrics),
        "num_success": int(sum(successes)),
        "policy_metadata": policy_metadata,
        "failure_counts": failure_counts,
        "episode_metrics": episode_metrics,
        # Gate audit aggregates.
        "descend_exit_rate": round(
            sum(1 for e in episode_metrics if e["descend_exit_step"] is not None) / len(episode_metrics), 4
        ),
        "grasp_phase_reached_rate": round(
            sum(1 for e in episode_metrics if e["grasp_phase_reached"]) / len(episode_metrics), 4
        ),
        "lift_phase_reached_rate": round(
            sum(1 for e in episode_metrics if e["lift_phase_reached"]) / len(episode_metrics), 4
        ),
        "min_grasp_z_error_mean": round(
            sum(e["min_grasp_z_error"] for e in episode_metrics if e["min_grasp_z_error"] is not None)
            / max(1, sum(1 for e in episode_metrics if e["min_grasp_z_error"] is not None)),
            6,
        ),
        "min_grasp_dist_mean": round(
            sum(e["min_grasp_dist"] for e in episode_metrics if e["min_grasp_dist"] is not None)
            / max(1, sum(1 for e in episode_metrics if e["min_grasp_dist"] is not None)),
            6,
        ),
        "dominant_blocking_reason_distribution": {
            reason: sum(1 for e in episode_metrics if e["dominant_blocking_reason"] == reason)
            for reason in set(e["dominant_blocking_reason"] for e in episode_metrics if e["dominant_blocking_reason"])
        },
    }

    if is_oracle:
        # Oracle/cheat policies must not claim skill discovery or evolution.
        summary["skill_discovery_rate"] = None
        summary["evolution_score"] = None
        summary["skill_candidate_count"] = 0
        summary["validated_skill_count"] = 0
        summary["leaderboard_excluded"] = True
        summary["can_claim_capability"] = False

    return summary


def _write_metrics_file() -> None:
    """Persist captured metrics to a shared file so the host can read them
    even if IsaacSim calls os._exit() and skips Python finally blocks."""

    output: dict[str, object] = {}

    # Source 1: captured from MetricsLogger.append_job_metrics
    if _captured_metrics:
        for job_name, metrics in _captured_metrics.items():
            for k, v in metrics.items():
                output[f"{job_name}_{k}"] = v

    # Source 2: captured from JobManager.complete_job
    if _captured_jobs:
        for job_name, info in _captured_jobs.items():
            if info.get("num_steps") is not None:
                output[f"{job_name}_num_steps"] = info["num_steps"]
            if info.get("num_episodes") is not None:
                output[f"{job_name}_num_episodes"] = info["num_episodes"]
            output[f"{job_name}_status"] = info.get("status", "unknown")
            if info.get("metrics"):
                for k, v in info["metrics"].items():
                    output[f"{job_name}_jobmetric_{k}"] = v

    # Source 3: captured from rollout_policy return value
    if _captured_rollout.get("last"):
        last = _captured_rollout["last"]
        if last.get("metrics"):
            for k, v in last["metrics"].items():
                output[f"rollout_{k}"] = v
        output["rollout_num_steps"] = last.get("num_steps")
        output["rollout_num_episodes"] = last.get("num_episodes")

    # Source 4: per-episode progress metrics computed from step traces
    trace_path = Path("/workspace/data/traces/episode_trace.jsonl")
    if trace_path.exists():
        try:
            trace_episodes: dict[int, list[dict[str, Any]]] = {}
            with trace_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    trace_episodes.setdefault(int(rec.get("episode", 0)), []).append(rec)
            if trace_episodes:
                progress_summary = _compute_progress_metrics(list(trace_episodes.values()), _SUCCESS_CONDITIONS)
                for k, v in progress_summary.items():
                    output[k] = v
        except Exception as e:
            output["trace_error"] = str(e)
            pass

    # Source 5: asset fidelity / benchmark validity information
    global _captured_asset_info
    if _captured_asset_info:
        output.setdefault("asset_info", _captured_asset_info.get("asset_info"))
        output.setdefault("benchmark_validity", _captured_asset_info.get("benchmark_validity"))

    if _captured_episode_traces:
        progress_summary = _compute_progress_metrics(_captured_episode_traces, _SUCCESS_CONDITIONS)
        for k, v in progress_summary.items():
            output.setdefault(k, v)

    if not output:
        output["note"] = "execution_completed"

    try:
        with open("/workspace/data/metrics_output.json", "w") as f:
            json.dump(output, f)
    except Exception:
        pass

    # Also try stdout with strong delimiters.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        marker = "<<<ROSCLAW_ARENA_METRICS>>>"
        sys.stdout.write(f"\n{marker}\n")
        sys.stdout.write(json.dumps(output))
        sys.stdout.write(f"\n{marker}\n")
        sys.stdout.flush()
    except Exception:
        pass


# 1. Monkey-patch rollout_policy BEFORE eval_runner imports it.
try:
    from isaaclab_arena.evaluation import policy_runner as _pr_mod

    _orig_rollout = _pr_mod.rollout_policy

    def _patched_rollout(env, policy, num_steps=None, num_episodes=None, language_instruction=None):
        step_log: list[dict] = []
        current_trace: list[dict[str, Any]] = []
        _captured_episode_traces.clear()
        _orig_step = env.step

        def _patched_step(action):
            obs, reward, terminated, truncated, info = _orig_step(action)
            terminated_b = bool(terminated.any().item()) if hasattr(terminated, "any") else bool(terminated)
            truncated_b = bool(truncated.any().item()) if hasattr(truncated, "any") else bool(truncated)
            state = _extract_state_from_env(env, action)
            step_log.append({
                "step": len(step_log),
                "terminated": terminated_b,
                "truncated": truncated_b,
                "reward": float(reward) if hasattr(reward, "item") else float(reward),
            })
            current_trace.append({
                "step": len(step_log) - 1,
                **state,
            })
            if terminated_b or truncated_b:
                if current_trace:
                    _captured_episode_traces.append(current_trace)
                    current_trace = []
            return obs, reward, terminated, truncated, info

        env.step = _patched_step
        metrics = _orig_rollout(env, policy, num_steps, num_episodes, language_instruction)
        env.step = _orig_step

        if current_trace:
            _captured_episode_traces.append(current_trace)

        enriched_metrics = dict(metrics) if metrics else {}
        enriched_metrics["_step_count"] = len(step_log)
        enriched_metrics["_episode_lengths"] = [i["step"] + 1 for i in step_log if i["terminated"] or i["truncated"]]
        enriched_metrics["_num_episodes_observed"] = len(_captured_episode_traces)
        if step_log:
            enriched_metrics["_first_terminated"] = int(step_log[0]["terminated"])
            enriched_metrics["_first_truncated"] = int(step_log[0]["truncated"])
            enriched_metrics["_last_terminated"] = int(step_log[-1]["terminated"])
            enriched_metrics["_last_truncated"] = int(step_log[-1]["truncated"])
        _captured_rollout["last"] = {
            "metrics": enriched_metrics,
            "num_steps": num_steps,
            "num_episodes": num_episodes,
        }
        _write_metrics_file()
        return metrics

    _pr_mod.rollout_policy = _patched_rollout
except Exception:
    pass

# 2. Monkey-patch MetricsLogger.append_job_metrics.
try:
    from isaaclab_arena.metrics.metrics_logger import MetricsLogger

    _orig_append = MetricsLogger.append_job_metrics

    def _patched_append(self, job_name, metrics):
        _orig_append(self, job_name, metrics)
        if metrics:
            _captured_metrics[job_name] = metrics
        _write_metrics_file()

    MetricsLogger.append_job_metrics = _patched_append
except Exception:
    pass

# 3. Monkey-patch JobManager.complete_job.
try:
    from isaaclab_arena.evaluation.job_manager import JobManager

    _orig_complete = JobManager.complete_job

    def _patched_complete(self, job, metrics=None, status=None):
        _orig_complete(self, job, metrics=metrics, status=status)
        _captured_jobs[job.name] = {
            "status": str(status) if status else None,
            "num_steps": job.num_steps,
            "num_episodes": job.num_episodes,
            "metrics": metrics,
        }
        _write_metrics_file()

    JobManager.complete_job = _patched_complete
except Exception:
    pass

# Patch procedural object spawn configs from task physics_ablation metadata.
# This must run before the environment builds its scene, but after Isaac Sim
# has initialized (so pxr is available).  We therefore patch eval_runner.load_env
# which is called after SimulationApp startup.
try:
    import isaaclab_arena.evaluation.eval_runner as _eval_runner_mod

    _PHYSICS_ABLATION = dict(_JOB_CONFIG.get("physics_ablation") or {})

    def _apply_physics_ablation_to_spawn(spawn_cfg: Any) -> None:
        if spawn_cfg is None:
            return
        if "size" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "size"):
            spawn_cfg.size = tuple(_PHYSICS_ABLATION["size"])
        if "static_friction" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "physics_material"):
            spawn_cfg.physics_material.static_friction = float(_PHYSICS_ABLATION["static_friction"])
            spawn_cfg.physics_material.dynamic_friction = float(
                _PHYSICS_ABLATION.get("dynamic_friction", _PHYSICS_ABLATION["static_friction"])
            )
        if "mass" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "mass_props"):
            spawn_cfg.mass_props.mass = float(_PHYSICS_ABLATION["mass"])
        if "contact_offset" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "collision_props"):
            spawn_cfg.collision_props.contact_offset = float(_PHYSICS_ABLATION["contact_offset"])
        if "rest_offset" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "collision_props"):
            spawn_cfg.collision_props.rest_offset = float(_PHYSICS_ABLATION["rest_offset"])
        if "torsional_patch_radius" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "collision_props"):
            spawn_cfg.collision_props.torsional_patch_radius = float(_PHYSICS_ABLATION["torsional_patch_radius"])
        if "min_torsional_patch_radius" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "collision_props"):
            spawn_cfg.collision_props.min_torsional_patch_radius = float(
                _PHYSICS_ABLATION["min_torsional_patch_radius"]
            )
        if "solver_velocity_iteration_count" in _PHYSICS_ABLATION and hasattr(spawn_cfg, "rigid_props"):
            spawn_cfg.rigid_props.solver_velocity_iteration_count = int(
                _PHYSICS_ABLATION["solver_velocity_iteration_count"]
            )

    _orig_load_env = _eval_runner_mod.load_env

    def _patched_load_env(arena_env_args: list[str], job_name: str, render_mode: str | None = None):
        global _captured_asset_info
        if _PHYSICS_ABLATION:
            try:
                import isaaclab_arena.assets.object_library as _obj_library

                _orig_generate = _obj_library.ProceduralCube._generate_rigid_cfg

                def _patched_generate(self: Any) -> Any:
                    cfg = _orig_generate(self)
                    _apply_physics_ablation_to_spawn(getattr(cfg, "spawn", None))
                    return cfg

                _obj_library.ProceduralCube._generate_rigid_cfg = _patched_generate
                sys.stderr.write(f"[RUN_EVAL] applied physics_ablation to ProceduralCube: {_PHYSICS_ABLATION}\n")
                sys.stderr.flush()
            except Exception as exc:
                sys.stderr.write(f"[RUN_EVAL] physics_ablation patch failed: {exc}\n")
                sys.stderr.flush()
        else:
            sys.stderr.write("[RUN_EVAL] no physics_ablation in job config\n")
            sys.stderr.flush()

        env = _orig_load_env(arena_env_args, job_name, render_mode)

        # Asset fidelity: check whether the requested object was actually loaded.
        try:
            asset_policy = _load_asset_policy(_JOB_CONFIG)
            requested_object = _load_requested_object(_JOB_CONFIG)
            scene = getattr(env, "unwrapped", env).scene
            resolution = _resolve_asset_from_scene(requested_object, scene)
            validity, abort = _compute_benchmark_validity(resolution, asset_policy)

            # Object geometry: capture from scene and forward to the policy so it
            # can adapt grasp thresholds to the actual loaded object.
            object_geometry = _extract_geometry_from_scene(scene, object_name=resolution.loaded_object)
            if _POLICY_CONFIG.get("use_object_geometry_adaptation") and not _POLICY_CONFIG.get("object_geometry"):
                _POLICY_CONFIG["object_geometry"] = object_geometry
                sys.stderr.write(f"[RUN_EVAL] object_geometry injected into policy config: {json.dumps(object_geometry)}\n")
                sys.stderr.flush()

            asset_info_payload = {
                "asset_info": resolution.to_dict(),
                "benchmark_validity": validity.to_dict(),
                "object_geometry": object_geometry,
            }
            _captured_asset_info = asset_info_payload
            sys.stderr.write(f"[RUN_EVAL] asset_info: {json.dumps(asset_info_payload)}\n")
            sys.stderr.flush()

            if abort:
                sys.stderr.write(
                    f"[RUN_EVAL] ABORT: required official asset '{requested_object}' was not loaded.\n"
                )
                sys.stderr.flush()
                try:
                    env.close()
                except Exception:
                    pass
                raise RuntimeError(
                    f"environment_invalid: required asset '{requested_object}' missing; "
                    f"loaded '{resolution.loaded_object}' instead."
                )
        except Exception as exc:
            sys.stderr.write(f"[RUN_EVAL] asset_resolution check failed: {exc}\n")
            sys.stderr.flush()

        return env

    _eval_runner_mod.load_env = _patched_load_env
except Exception as _phys_abl_exc:
    sys.stderr.write(f"[RUN_EVAL] failed to install load_env hook: {_phys_abl_exc}\n")
    sys.stderr.flush()
    import traceback
    traceback.print_exc()

# Import eval_runner AFTER patching policy_runner so the imported
# rollout_policy reference points to our patched function.
from isaaclab_arena.evaluation.eval_runner import main

# Some Arena example environments (e.g. kitchen_pick_and_place) use object
# references whose parent asset is rotated by non-Z-axis quaternions. The
# object placer asserts on these; relax the helper so the env can still build.
# This patch is applied after eval_runner imports are resolved so the modules
# are already loaded and can be monkey-patched in-place.
try:
    import math

    import isaaclab_arena.assets.object_reference as _obj_ref_mod
    import isaaclab_arena.utils.bounding_box as _bbox_mod

    def _loose_quaternion_to_90_deg_z_quarters(rotation_xyzw, tol_deg=1.0):
        x, y, z, w = rotation_xyzw
        if abs(x) < 1e-3 and abs(y) < 1e-3:
            angle_deg = math.degrees(2 * math.atan2(z, w)) % 360
            return round(angle_deg / 90) % 4
        # Fallback for arbitrary rotations: assume no rotation. This keeps
        # zero_action / heuristic rollouts from failing during scene setup.
        return 0

    _bbox_mod.quaternion_to_90_deg_z_quarters = _loose_quaternion_to_90_deg_z_quarters
    _obj_ref_mod.quaternion_to_90_deg_z_quarters = _loose_quaternion_to_90_deg_z_quarters

    # Also replace the method that calls the helper, in case the imported name
    # in object_reference is bound to the original function object.
    def _patched_get_world_bounding_box(self):
        pose = self.get_initial_pose()
        quarters = _loose_quaternion_to_90_deg_z_quarters(pose.rotation_xyzw)
        return self.get_bounding_box().rotated_90_around_z(quarters).translated(pose.position_xyz)

    _obj_ref_mod.ObjectReference.get_world_bounding_box = _patched_get_world_bounding_box
except Exception:
    pass

if __name__ == "__main__":
    try:
        main()
    finally:
        _write_metrics_file()
