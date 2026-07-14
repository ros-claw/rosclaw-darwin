#!/usr/bin/env python3
"""Standalone probe worker executed by the LeRobot runtime Python.

This script must not depend on ``rosclaw-darwin`` being installed.  It may
use only the Python standard library plus numpy/PIL/lerobot when available
in the target runtime.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "rosclaw.darwin.lerobot_probe.v1"


def _try_import(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _lerobot_version() -> str | None:
    lerobot = _try_import("lerobot")
    if lerobot is None:
        return None
    version = getattr(lerobot, "__version__", None)
    if version:
        return version
    try:
        return importlib.metadata.version("lerobot")
    except Exception:
        return None


def _module_available(module_path: str) -> bool:
    try:
        return importlib.util.find_spec(module_path) is not None
    except ModuleNotFoundError:
        return False


def _cli_available() -> bool:
    # When the worker is launched from a virtual-env python, the matching
    # lerobot-eval executable lives next to sys.executable even if PATH is
    # not propagated to the subprocess.
    exe_dir = Path(sys.executable).parent
    if (exe_dir / "lerobot-eval").exists() or (exe_dir / "lerobot-eval.exe").exists():
        return True
    if shutil.which("lerobot-eval"):
        return True
    # LeRobot 0.3.x keeps the eval entry point in ``lerobot.scripts.eval``,
    # while 0.4.x uses ``lerobot.scripts.lerobot_eval``.
    return _module_available("lerobot.scripts.eval") or _module_available(
        "lerobot.scripts.lerobot_eval"
    )


def _policy_probe(policy_path: str, allow_network: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": policy_path,
        "local_exists": False,
        "config_found": False,
        "weights_found": False,
        "remote_exists": None,
    }
    if not policy_path:
        return result

    local_path = Path(policy_path)
    if local_path.exists():
        result["local_exists"] = True
        result["config_found"] = (local_path / "config.json").exists()
        weight_suffixes = {".safetensors", ".pt", ".pth", ".bin", ".ckpt"}
        for child in local_path.iterdir():
            if child.is_file() and child.suffix.lower() in weight_suffixes:
                result["weights_found"] = True
                break
        return result

    if allow_network and "/" in policy_path:
        hf_hub = _try_import("huggingface_hub")
        if hf_hub is not None:
            try:
                hf_hub.repo_exists(policy_path)
                result["remote_exists"] = True
            except Exception:
                result["remote_exists"] = False
    return result


def _env_probe(env_type: str) -> dict[str, Any]:
    result: dict[str, Any] = {"type": env_type, "registered": None}
    if not env_type:
        result["registered"] = False
        return result

    # Try several LeRobot APIs for environment registration.
    envs = _try_import("lerobot.common.envs.utils")
    if envs is not None:
        for attr in ("envs", "available_envs", "ENVIRONMENT_TYPES", "registered_envs"):
            registry = getattr(envs, attr, None)
            if registry is not None:
                if isinstance(registry, dict):
                    result["registered"] = env_type in registry
                    return result
                if isinstance(registry, (list, tuple, set)):
                    result["registered"] = env_type in registry
                    return result

    # LeRobot 0.3.x registers environments through ``lerobot.envs.configs.EnvConfig``
    # draccus choice registry.
    try:
        from lerobot.envs.configs import EnvConfig

        choices = EnvConfig.get_known_choices()
        if isinstance(choices, dict) and env_type in choices:
            result["registered"] = True
            return result
    except Exception:
        pass

    result["registered"] = None  # unknown: could not inspect registry
    return result


def _device_probe(requested: str) -> dict[str, Any]:
    result: dict[str, Any] = {"requested": requested, "available": None}
    torch = _try_import("torch")
    if torch is None:
        result["available"] = None
        return result

    requested = (requested or "cpu").lower()
    if requested == "cpu":
        result["available"] = True
    elif requested.startswith("cuda"):
        result["available"] = torch.cuda.is_available()
    else:
        # Other devices (e.g. mps) are reported as unknown.
        result["available"] = None
    return result


def _torch_version() -> str | None:
    torch = _try_import("torch")
    if torch is None:
        return None
    return getattr(torch, "__version__", None)


def _cuda_info() -> dict[str, Any]:
    torch = _try_import("torch")
    if torch is None:
        return {"available": None, "device_count": 0, "current_device_name": None}
    if not torch.cuda.is_available():
        return {"available": False, "device_count": 0, "current_device_name": None}
    try:
        name = torch.cuda.get_device_name(torch.cuda.current_device())
    except Exception:
        name = None
    return {
        "available": True,
        "device_count": torch.cuda.device_count(),
        "current_device_name": name,
    }


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _benchmark_package(env_type: str) -> dict[str, Any]:
    """Probe for the environment-specific benchmark package needed by LeRobot."""
    result: dict[str, Any] = {"env_type": env_type, "package": None, "available": None}
    if not env_type:
        result["available"] = None
        return result

    mapping = {
        "pusht": "gym_pusht",
        "push_t": "gym_pusht",
        "libero": "libero",
        "metaworld": "metaworld",
        "robomme": "robomme",
        "robotwin": "robotwin",
        "isaaclab": "isaaclab",
        "arena": "isaaclab",
    }
    package = mapping.get(env_type.lower())
    result["package"] = package
    if package is None:
        result["available"] = None
        return result
    result["available"] = _module_available(package)
    return result


def _headless_env() -> dict[str, str | None]:
    return {
        "MUJOCO_GL": os.environ.get("MUJOCO_GL"),
        "EGL_DEVICE_ID": os.environ.get("EGL_DEVICE_ID"),
        "DISPLAY": os.environ.get("DISPLAY"),
    }


def _derive_status(policy: dict, env: dict, device: dict, cli_ok: bool) -> str:
    if not cli_ok:
        return "error"
    if policy.get("path") and not policy.get("local_exists"):
        # A local policy path that does not exist is an error when we cannot
        # transparently fetch it.
        return "degraded"
    if env.get("registered") is False:
        return "error"
    if device.get("available") is False:
        return "error"

    unknowns = [
        env.get("registered") is None,
        device.get("available") is None,
        policy.get("local_exists") is False,
    ]
    if any(unknowns):
        return "degraded"
    return "ok"


def probe(request: dict[str, Any]) -> dict[str, Any]:
    """Run the probe and return a JSON-serializable result."""
    policy_path = request.get("policy_path", "")
    env_type = request.get("env_type", "")
    device = request.get("device", "cpu")
    allow_network = bool(request.get("allow_network", False))

    messages: list[str] = []
    cli_ok = _cli_available()
    if not cli_ok:
        messages.append("lerobot-eval CLI or module not found")

    lerobot_version = _lerobot_version()
    if lerobot_version is None:
        messages.append("lerobot package not importable in runtime")

    policy = _policy_probe(policy_path, allow_network=allow_network)
    environment = _env_probe(env_type)
    device_info = _device_probe(device)
    torch_version = _torch_version()
    cuda_info = _cuda_info()
    ffmpeg_ok = _ffmpeg_available()
    benchmark_pkg = _benchmark_package(env_type)
    headless = _headless_env()

    status = _derive_status(policy, environment, device_info, cli_ok)
    compatibility = (
        "compatible"
        if status == "ok"
        else ("incompatible" if status == "error" else "unknown")
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "compatibility": compatibility,
        "lerobot_version": lerobot_version,
        "torch_version": torch_version,
        "policy": policy,
        "environment": environment,
        "device": device_info,
        "cuda": cuda_info,
        "ffmpeg_available": ffmpeg_ok,
        "benchmark_package": benchmark_pkg,
        "headless": headless,
        "messages": messages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe a LeRobot runtime for eval readiness."
    )
    parser.add_argument(
        "--request-json",
        required=True,
        help="JSON string with fields policy_path, env_type, device, allow_network.",
    )
    args = parser.parse_args(argv)

    try:
        request = json.loads(args.request_json)
    except json.JSONDecodeError as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "lerobot_version": None,
            "policy": {},
            "environment": {},
            "device": {},
            "messages": [f"Invalid request JSON: {exc}"],
        }
        print(json.dumps(result, indent=2))
        return 1

    result = probe(request)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] != "error" else 2


if __name__ == "__main__":
    sys.exit(main())
