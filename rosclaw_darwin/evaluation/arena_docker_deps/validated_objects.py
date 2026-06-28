"""Validated object specifications for local ROSClaw OOD benchmarks.

Arena's ``ProceduralCube`` fallback is not a valid interactive rigid body by default
(collision disabled, degenerate bounding box).  The specs here describe the
parameters for a *rosclaw-validated* cuboid that the container-side patch in
``run_eval.py`` forces into a graspable state by attaching collision properties.

These objects are explicitly **not** official Arena assets.  They exist only for
local diagnostic runs where we need a controllable OOD cube while waiting for
Arena to provide a valid procedural/fallback object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidatedCuboidSpec:
    """Specification for a validated procedural cube OOD object.

    The fields map directly to the ``physics_ablation`` block that is forwarded
    into the Arena container, with the addition of the ``rosclaw_valid_cube``
    marker that tells ``run_eval.py`` to force-create ``collision_props``.
    """

    name: str
    """Human-readable name for the variant (e.g. ``valid_cube_005``)."""

    size: tuple[float, float, float]
    """Cube side lengths in metres."""

    mass: float
    """Mass in kilograms."""

    static_friction: float = 0.5
    """Static friction coefficient."""

    dynamic_friction: float | None = None
    """Dynamic friction coefficient; defaults to ``static_friction``."""

    restitution: float | None = None
    """Restitution coefficient; kept None to use Arena default."""

    @property
    def dynamic_friction_value(self) -> float:
        """Return the dynamic friction, falling back to static friction."""
        return self.dynamic_friction if self.dynamic_friction is not None else self.static_friction

    def to_physics_ablation(self) -> dict[str, Any]:
        """Return the container-side physics_ablation dict for this cube."""
        ablation: dict[str, Any] = {
            "size": list(self.size),
            "mass": self.mass,
            "static_friction": self.static_friction,
            "dynamic_friction": self.dynamic_friction_value,
            "rosclaw_valid_cube": True,
        }
        if self.restitution is not None:
            ablation["restitution"] = self.restitution
        return ablation


# Convenience registry of the initial v1.8 valid-cube diagnostic variants.
# These are intentionally small perturbations around the dex_cube size so that
# we can isolate size/mass/friction effects without leaving the reachable workspace.
VALIDATED_CUBE_VARIANTS: dict[str, ValidatedCuboidSpec] = {
    "valid_cube_004": ValidatedCuboidSpec(
        name="valid_cube_004",
        size=(0.04, 0.04, 0.04),
        mass=0.04,
    ),
    "valid_cube_005": ValidatedCuboidSpec(
        name="valid_cube_005",
        size=(0.05, 0.05, 0.05),
        mass=0.05,
    ),
    "valid_cube_006": ValidatedCuboidSpec(
        name="valid_cube_006",
        size=(0.06, 0.06, 0.06),
        mass=0.06,
    ),
    "valid_cube_008": ValidatedCuboidSpec(
        name="valid_cube_008",
        size=(0.08, 0.08, 0.08),
        mass=0.08,
    ),
    "valid_cube_010": ValidatedCuboidSpec(
        name="valid_cube_010",
        size=(0.10, 0.10, 0.10),
        mass=0.10,
    ),
    "valid_cube_low_friction": ValidatedCuboidSpec(
        name="valid_cube_low_friction",
        size=(0.05, 0.05, 0.05),
        mass=0.05,
        static_friction=0.05,
        dynamic_friction=0.05,
    ),
    "valid_cube_heavy": ValidatedCuboidSpec(
        name="valid_cube_heavy",
        size=(0.05, 0.05, 0.05),
        mass=0.50,
    ),
}


def get_validated_cube_spec(variant: str) -> ValidatedCuboidSpec:
    """Return a registered validated cube spec by variant name."""
    if variant not in VALIDATED_CUBE_VARIANTS:
        raise KeyError(f"Unknown validated cube variant: {variant!r}")
    return VALIDATED_CUBE_VARIANTS[variant]
