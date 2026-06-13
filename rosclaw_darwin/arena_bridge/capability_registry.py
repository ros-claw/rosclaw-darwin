"""Arena capability registry: declarative mapping from ROSClaw tasks to Arena environments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ArenaCapabilityRegistry:
    """Loads and queries the Arena capability registry YAML."""

    _DEFAULT_PATH: Path = Path(__file__).parent.parent.parent / "configs" / "arena" / "capability_registry.yaml"

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ArenaCapabilityRegistry":
        target = Path(path) if path else cls._DEFAULT_PATH
        if not target.exists():
            raise FileNotFoundError(f"Arena capability registry not found: {target}")
        data = yaml.safe_load(target.read_text())
        if not isinstance(data, dict):
            raise ValueError("Arena capability registry must be a YAML mapping")
        return cls(data)

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def list_environments(self) -> list[str]:
        return list(self._data.get("environments", {}).keys())

    def get(self, env_name: str) -> dict[str, Any]:
        return dict(self._data.get("environments", {}).get(env_name, {}))

    def _map(self, category: str, name: str) -> str:
        return self._data.get("mappings", {}).get(category, {}).get(name, name)

    def map_object(self, rosclaw_name: str) -> str:
        return self._map("objects", rosclaw_name)

    def map_scene(self, rosclaw_name: str) -> str:
        return self._map("scenes", rosclaw_name)

    def map_robot(self, rosclaw_name: str) -> str:
        return self._map("robots", rosclaw_name)
