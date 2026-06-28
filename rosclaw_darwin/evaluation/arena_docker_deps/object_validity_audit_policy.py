# Container-side object validity audit policy.
#
# This policy does not try to grasp or lift.  It steps the environment a small
# number of times, records detailed object-state metadata at each step, and
# writes it to the shared episode trace so the host can audit whether the
# procedural / OOD object is a valid interactive rigid body.

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Any

import gymnasium as gym
import torch
from gymnasium.spaces.dict import Dict as GymSpacesDict

try:
    from isaaclab_arena.policy.policy_base import PolicyBase
except Exception:  # pragma: no cover - host side does not have IsaacLab-Arena installed
    class PolicyBase:
        """Minimal stub so the policy file can be imported in host tests."""

        def __init__(self, config):
            self.config = config


_TRACE_DIR = os.environ.get("ROSCLAW_TRACE_DIR", "/workspace/data/traces")
_TRACE_PATH = os.path.join(_TRACE_DIR, "episode_trace.jsonl")


try:
    os.makedirs(_TRACE_DIR, exist_ok=True)
except Exception:
    pass


def _append_trace(step: dict[str, Any], clear_on_step_zero: bool = True) -> None:
    """Append a scalar step record to the shared trace file.

    When ``clear_on_step_zero`` is ``False`` the trace is never truncated, which
    allows a single Arena container to audit multiple episodes/seeds in one run.
    """
    try:
        truncate = step.get("step") == 0 and clear_on_step_zero
        mode = "w" if truncate else "a"
        with open(_TRACE_PATH, mode, encoding="utf-8") as f:
            f.write(json.dumps(step) + "\n")
    except Exception as e:
        print(f"[TRACE_WRITE_ERROR] {e}", file=sys.stderr)


def _as_tuple(value: Any) -> tuple[float, ...]:
    """Normalise a scalar/list/tensor to a tuple of floats."""
    if isinstance(value, (list, tuple)):
        return tuple(float(v) for v in value)
    try:
        if isinstance(value, torch.Tensor):
            return tuple(float(v) for v in value.flatten().tolist())
    except Exception:
        pass
    return (float(value),)


def _quat_to_yaw(q: torch.Tensor) -> float:
    """Yaw angle from a quaternion in Arena's (x, y, z, w) ordering."""
    x, y, z, w = q[0].item(), q[1].item(), q[2].item(), q[3].item()
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _find_spawn_attr(obj: Any, attr_name: str) -> Any:
    """Look for ``attr_name`` on ``obj.spawn``, ``obj.cfg``, and ``obj.cfg.spawn``.

    IsaacLab scene objects expose the constructed object cfg via ``obj.cfg``; the
    spawn primitives (CuboidCfg, etc.) live at ``obj.cfg.spawn``.  Some objects
    also expose the final spawn config as ``obj.spawn``.  We check all three
    locations so the audit can read collision/mass/friction/size for both USD
    assets and procedural primitives.
    """
    for src in (getattr(obj, "spawn", None), getattr(obj, "cfg", None)):
        if src is None:
            continue
        val = getattr(src, attr_name, None)
        if val is not None:
            return val
        nested = getattr(src, "spawn", None)
        if nested is not None:
            val = getattr(nested, attr_name, None)
            if val is not None:
                return val
    return None


@dataclass
class ObjectValidityAuditPolicyArgs:
    """Configuration for the audit policy."""

    audit_steps: int = 11
    table_z: float = 0.18
    object_name_hint: str | None = None
    clear_trace_on_reset: bool = True

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "ObjectValidityAuditPolicyArgs":
        return cls(
            audit_steps=getattr(args, "audit_steps", 11),
            table_z=getattr(args, "table_z", 0.18),
            object_name_hint=getattr(args, "object_name_hint", None),
            clear_trace_on_reset=getattr(args, "clear_trace_on_reset", True),
        )


class ObjectValidityAuditPolicy(PolicyBase):
    """Passive diagnostic policy that records object validity metadata."""

    name = "object_validity_audit"
    config_class = ObjectValidityAuditPolicyArgs

    def __init__(self, config: ObjectValidityAuditPolicyArgs):
        super().__init__(config)
        self._step = 0
        self._config = config
        self._object_name_hint = config.object_name_hint
        self._episode_idx = 0
        self._clear_trace_on_reset = config.clear_trace_on_reset
        try:
            if os.path.exists(_TRACE_PATH):
                os.remove(_TRACE_PATH)
        except Exception:
            pass

    def _find_object(self, env: gym.Env) -> tuple[Any, str] | tuple[None, str]:
        """Find the manipulation object in the scene."""
        try:
            scene = getattr(env, "unwrapped", env).scene
        except Exception:
            return None, "unknown"
        if scene is None:
            return None, "unknown"

        names = {"object", "dex_cube", "cube", "procedural_cube"}
        if self._object_name_hint:
            names.add(self._object_name_hint)

        for key in scene.keys():
            name = str(key)
            if name not in names:
                continue
            try:
                obj = scene[key]
                data = getattr(obj, "data", None)
                if data is not None and hasattr(data, "root_state_w"):
                    return obj, name
            except Exception:
                continue
        return None, "unknown"

    def _extract_audit_record(
        self, env: gym.Env, step: int
    ) -> dict[str, Any]:
        """Build an object-validity trace record for the current step."""
        obj, object_name = self._find_object(env)
        record: dict[str, Any] = {
            "step": step,
            "episode": self._episode_idx,
            "audit": True,
            "object_name": object_name,
            "object_found": obj is not None,
        }
        if obj is None:
            return record

        try:
            data = obj.data
            device = data.root_state_w.device
            root_state = data.root_state_w.squeeze()
            if root_state.ndim > 1:
                root_state = root_state[0]

            pos = root_state[:3].tolist()
            quat = root_state[3:7].tolist()
            lin_vel = root_state[7:10].tolist() if root_state.numel() >= 10 else [0.0, 0.0, 0.0]
            ang_vel = root_state[10:13].tolist() if root_state.numel() >= 13 else [0.0, 0.0, 0.0]

            record["object_x"] = float(pos[0])
            record["object_y"] = float(pos[1])
            record["object_z"] = float(pos[2])
            record["object_yaw"] = _quat_to_yaw(torch.tensor(quat, device=device))
            record["object_root_pos"] = [float(v) for v in pos]
            record["object_root_quat"] = [float(v) for v in quat]
            record["object_linear_velocity"] = [float(v) for v in lin_vel]
            record["object_angular_velocity"] = [float(v) for v in ang_vel]
            record["object_above_table"] = float(pos[2]) > self._config.table_z
        except Exception as exc:
            record["root_state_error"] = str(exc)

        # Spawn / rigid body / collision configuration.
        try:
            rigid_props = _find_spawn_attr(obj, "rigid_props")
            collision_props = _find_spawn_attr(obj, "collision_props")
            mass_props = _find_spawn_attr(obj, "mass_props")
            physics_material = _find_spawn_attr(obj, "physics_material")

            # A rigid body is considered enabled if it either has explicit rigid
            # props without gravity disabled, or has collision props (which only
            # make sense on a rigid body).
            rigid_enabled = False
            if rigid_props is not None:
                rigid_enabled = getattr(rigid_props, "disable_gravity", False) is not True
            elif collision_props is not None:
                rigid_enabled = True
            record["rigid_body_enabled"] = rigid_enabled

            # Collision is enabled when a collision config exists and is not
            # explicitly disabled.  ``collision_enabled=None`` is the default and
            # means the USD default (enabled) will be used.
            collision_enabled = False
            if collision_props is not None:
                collision_enabled = getattr(collision_props, "collision_enabled", None) is not False
            record["collision_enabled"] = collision_enabled

            if mass_props is not None:
                record["mass"] = float(getattr(mass_props, "mass", 0.0))

            if physics_material is not None:
                record["static_friction"] = float(getattr(physics_material, "static_friction", 0.0))
                record["dynamic_friction"] = float(getattr(physics_material, "dynamic_friction", 0.0))
        except Exception as exc:
            record["spawn_props_error"] = str(exc)

        # Bounding box.  Procedural primitives (CuboidCfg) carry their geometry
        # via ``size`` on the spawn config; USD assets expose it via
        # ``get_bounding_box``.  Prefer the explicit spawn size when present.
        try:
            pos = [
                record.get("object_x", 0.0),
                record.get("object_y", 0.0),
                record.get("object_z", 0.0),
            ]
            size = _find_spawn_attr(obj, "size")
            bbox = None
            if size is not None:
                extent = _as_tuple(size)
                if len(extent) >= 3 and all(e > 0 for e in extent):
                    record["bbox_extent"] = [float(extent[0]), float(extent[1]), float(extent[2])]
                    half = [float(e) / 2.0 for e in extent]
                    record["bbox_world_min"] = [pos[i] - half[i] for i in range(3)]
                    record["bbox_world_max"] = [pos[i] + half[i] for i in range(3)]
            elif hasattr(obj, "get_bounding_box"):
                bbox = obj.get_bounding_box()
            if bbox is not None:
                upper = _as_tuple(getattr(bbox, "upper", None) or [0.0, 0.0, 0.0])
                lower = _as_tuple(getattr(bbox, "lower", None) or [0.0, 0.0, 0.0])
                if len(upper) >= 3 and len(lower) >= 3:
                    record["bbox_world_min"] = [float(v) for v in lower]
                    record["bbox_world_max"] = [float(v) for v in upper]
                    record["bbox_extent"] = [
                        float(upper[0] - lower[0]),
                        float(upper[1] - lower[1]),
                        float(upper[2] - lower[2]),
                    ]
        except Exception as exc:
            record["bbox_error"] = str(exc)

        # Metric / policy index introspection (best-effort).
        try:
            env_unwrapped = getattr(env, "unwrapped", env)
            if hasattr(env_unwrapped, "_object"):
                record["policy_object_index"] = id(env_unwrapped._object)
            if hasattr(env_unwrapped, "scene") and object_name in env_unwrapped.scene:
                record["metric_object_index"] = id(env_unwrapped.scene[object_name])
            record["trace_object_index"] = id(obj)
        except Exception:
            pass

        return record

    def get_action(self, env: gym.Env, observation: GymSpacesDict) -> torch.Tensor:
        step = self._step
        self._step += 1

        # Record object state at step 0, 1, 2, 5, 10 and then every 10 steps.
        if step <= 10 or step % 10 == 0:
            try:
                record = self._extract_audit_record(env, step)
                _append_trace(record, clear_on_step_zero=self._clear_trace_on_reset)
            except Exception as exc:
                _append_trace({"step": step, "audit_error": str(exc)}, clear_on_step_zero=self._clear_trace_on_reset)

        # Neutral action: hold position, keep gripper open, do not disturb object.
        action = torch.zeros(env.action_space.shape, device=torch.device(env.unwrapped.device))
        return action

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        self._step = 0
        self._episode_idx += 1
        if self._clear_trace_on_reset:
            try:
                if os.path.exists(_TRACE_PATH):
                    os.remove(_TRACE_PATH)
            except Exception:
                pass

    @staticmethod
    def add_args_to_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--audit-steps", type=int, default=11)
        parser.add_argument("--table-z", type=float, default=0.18)
        parser.add_argument("--object-name-hint", type=str, default=None)
        parser.add_argument(
            "--clear-trace-on-reset",
            dest="clear_trace_on_reset",
            action="store_true",
            default=True,
            help="Remove the trace file on every environment reset (default).",
        )
        parser.add_argument(
            "--no-clear-trace-on-reset",
            dest="clear_trace_on_reset",
            action="store_false",
            help="Append trace records across episodes so multiple seeds can be audited in one container.",
        )
        return parser

    @staticmethod
    def from_args(args: argparse.Namespace) -> "ObjectValidityAuditPolicy":
        return ObjectValidityAuditPolicy(ObjectValidityAuditPolicyArgs.from_cli_args(args))
