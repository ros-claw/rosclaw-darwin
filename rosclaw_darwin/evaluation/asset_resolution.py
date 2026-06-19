"""Asset resolution and fallback semantics for Arena evaluation.

This module separates "official" Arena asset results from fallback/diagnostic
results so that silent asset substitution does not contaminate benchmark claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AssetResolution:
    """Result of resolving a requested object name to a loadable Arena asset."""

    requested_object: str
    loaded_object: str
    asset_source: str  # e.g. "usd_asset", "procedural_fallback", "unknown"
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetResolution":
        return cls(
            requested_object=data.get("requested_object", "unknown"),
            loaded_object=data.get("loaded_object", "unknown"),
            asset_source=data.get("asset_source", "unknown"),
            asset_path=data.get("asset_path"),
            asset_fallback_used=bool(data.get("asset_fallback_used", False)),
            fallback_reason=data.get("fallback_reason"),
            official_asset=bool(data.get("official_asset", False)),
        )


@dataclass
class AssetPolicy:
    """Policy configured in a Task YAML to control asset loading behavior."""

    require_official_asset: bool = False
    allow_procedural_fallback: bool = True
    diagnostic_variant: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_official_asset": self.require_official_asset,
            "allow_procedural_fallback": self.allow_procedural_fallback,
            "diagnostic_variant": self.diagnostic_variant,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AssetPolicy":
        if data is None:
            return cls()
        return cls(
            require_official_asset=bool(data.get("require_official_asset", False)),
            allow_procedural_fallback=bool(data.get("allow_procedural_fallback", True)),
            diagnostic_variant=bool(data.get("diagnostic_variant", False)),
        )


@dataclass
class BenchmarkValidity:
    """Whether a result can be claimed as an official benchmark."""

    can_claim_official_benchmark: bool = False
    validity_scope: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_claim_official_benchmark": self.can_claim_official_benchmark,
            "validity_scope": self.validity_scope,
        }


def resolve_asset_from_scene(
    requested_object: str,
    asset_policy: AssetPolicy,
    scene: Any,
) -> AssetResolution:
    """Inspect an Arena scene and determine whether the requested object was loaded.

    This runs inside the Arena process (host or container) where the scene has
    already been built.
    """
    # Map ROSClaw abstract names to the concrete Arena names we expect in the scene.
    _EXPECTED_PRIM_NAMES: dict[str, set[str]] = {
        "dex_cube": {"dex_cube", "cube"},
        "cube": {"dex_cube", "cube"},
        "procedural_cube": {"procedural_cube"},
    }

    expected_names = _EXPECTED_PRIM_NAMES.get(requested_object, {requested_object})

    loaded_object = "unknown"
    asset_path: str | None = None
    fallback_used = False
    fallback_reason: str | None = None
    official_asset = False

    # Try to read scene keys if available.
    try:
        scene_keys = list(scene.keys())
    except Exception:
        scene_keys = []

    for key in scene_keys:
        key_str = str(key)
        if key_str in expected_names:
            loaded_object = key_str
            break

    # If we didn't find the requested object by name, check whether a procedural
    # cube was substituted.
    if loaded_object == "unknown":
        for key in scene_keys:
            key_str = str(key)
            if "procedural" in key_str or key_str == "procedural_cube":
                loaded_object = "procedural_cube"
                break

    # Determine source and fallback status.
    if loaded_object == requested_object or (
        requested_object in ("cube",) and loaded_object == "dex_cube"
    ):
        asset_source = "usd_asset" if loaded_object == "dex_cube" else "registered_asset"
        official_asset = True
        fallback_used = False
    elif loaded_object == "procedural_cube":
        asset_source = "procedural_fallback"
        fallback_used = True
        fallback_reason = "dex_cube_asset_missing"
        official_asset = False
    else:
        asset_source = "unknown"
        fallback_used = loaded_object != requested_object
        if fallback_used:
            fallback_reason = f"loaded_{loaded_object}_instead_of_{requested_object}"
        official_asset = False

    # Look for a USD path on the loaded asset.
    try:
        obj = scene.get(loaded_object) if hasattr(scene, "get") else None
        if obj is not None:
            path = getattr(obj, "usd_path", None)
            if path:
                asset_path = str(path)
    except Exception:
        pass

    return AssetResolution(
        requested_object=requested_object,
        loaded_object=loaded_object,
        asset_source=asset_source,
        asset_path=asset_path,
        asset_fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        official_asset=official_asset,
    )


def compute_benchmark_validity(
    resolution: AssetResolution,
    asset_policy: AssetPolicy,
) -> tuple[BenchmarkValidity, bool]:
    """Return benchmark validity and whether the run should be aborted.

    The boolean ``abort`` is True when the policy requires the official asset but
    a fallback was used.
    """
    if resolution.official_asset and not asset_policy.diagnostic_variant:
        return BenchmarkValidity(
            can_claim_official_benchmark=True,
            validity_scope="official_arena_asset",
        ), False

    if resolution.asset_fallback_used:
        if asset_policy.require_official_asset and not asset_policy.allow_procedural_fallback:
            return BenchmarkValidity(
                can_claim_official_benchmark=False,
                validity_scope="environment_invalid",
            ), True
        return BenchmarkValidity(
            can_claim_official_benchmark=False,
            validity_scope="asset_fidelity_diagnostic",
        ), False

    # Diagnostic variant (e.g. explicit procedural_cube OOD task).
    if asset_policy.diagnostic_variant:
        return BenchmarkValidity(
            can_claim_official_benchmark=False,
            validity_scope="ood_diagnostic",
        ), False

    return BenchmarkValidity(
        can_claim_official_benchmark=False,
        validity_scope="unknown",
    ), False


def load_asset_policy(job_config: dict[str, Any]) -> AssetPolicy:
    """Read the asset_policy block from a job config (task metadata)."""
    # Try direct task metadata if present (rare in container).
    policy_dict = job_config.get("asset_policy")
    if policy_dict is None:
        # Host-side adapter forwards it under task metadata or native config.
        metadata = job_config.get("metadata") or {}
        policy_dict = metadata.get("asset_policy")
    return AssetPolicy.from_dict(policy_dict)


def load_requested_object(job_config: dict[str, Any]) -> str:
    """Determine the object the task originally requested."""
    arena_env_args = job_config.get("arena_env_args") or {}
    obj = arena_env_args.get("object")
    if obj:
        return str(obj)
    # Fallback: inspect objects list from task metadata (forwarded by adapter).
    metadata = job_config.get("metadata") or {}
    objects = metadata.get("objects") or []
    if objects:
        return str(objects[0].get("name", "unknown"))
    return "unknown"
