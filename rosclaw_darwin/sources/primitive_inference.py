"""Infer TDL primitives and object affordances from task metadata."""

from __future__ import annotations

from rosclaw_darwin.tdl.schema import ObjectSpec, Primitive

# Keywords that hint at manipulation primitives.
_PRIMITIVE_KEYWORDS: dict[str, list[str]] = {
    "Pick": ["pick", "grasp", "take", "grab", "hold"],
    "Lift": ["lift", "raise", "elevate"],
    "Place": ["place", "put", "set", "drop", "move", "insert", "stack", "pour"],
    "Open": ["open", "unlock"],
    "Close": ["close", "shut", "lock"],
    "Press": ["press", "push", "switch", "toggle"],
    "Sort": ["sort", "classify", "organize", "separate"],
    "Navigate": ["navigate", "go to", "move to", "approach", "walk to"],
}

# Object category / name → affordance hints.
_AFFORDANCE_MAP: dict[str, list[str]] = {
    "bottle": ["graspable", "movable", "liquid"],
    "cup": ["graspable", "movable", "liquid", "container"],
    "mug": ["graspable", "movable", "liquid", "container"],
    "glass": ["graspable", "movable", "liquid", "container"],
    "can": ["graspable", "movable", "container"],
    "bowl": ["graspable", "movable", "container", "surface"],
    "plate": ["graspable", "movable", "surface"],
    "spoon": ["graspable", "movable"],
    "fork": ["graspable", "movable"],
    "knife": ["graspable", "movable"],
    "box": ["graspable", "movable", "container", "surface"],
    "bin": ["graspable", "movable", "container", "surface"],
    "container": ["graspable", "movable", "container", "surface"],
    "basket": ["graspable", "movable", "container", "surface"],
    "drawer": ["openable", "closeable", "articulated", "container"],
    "door": ["openable", "closeable", "articulated"],
    "fridge": ["openable", "closeable", "articulated", "container"],
    "cabinet": ["openable", "closeable", "articulated", "container"],
    "microwave": ["openable", "closeable", "articulated", "container"],
    "button": ["pressable"],
    "switch": ["pressable"],
    "table": ["surface"],
    "counter": ["surface"],
    "shelf": ["surface"],
    "chair": ["surface"],
    "banana": ["graspable", "movable", "deformable"],
    "apple": ["graspable", "movable"],
    "orange": ["graspable", "movable"],
    "bread": ["graspable", "movable", "deformable"],
    "cube": ["graspable", "movable"],
    "sphere": ["graspable", "movable"],
    "cylinder": ["graspable", "movable"],
}


def _tokenize(text: str) -> set[str]:
    """Return lowercase tokens, splitting CamelCase and underscores."""
    import re
    # Split CamelCase and underscores, then extract alphabetic tokens.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return set(re.findall(r"[a-z]+", spaced.lower()))


def infer_object_affordances(name: str, category: str | None = None) -> list[str]:
    """Infer affordances from object name and category."""
    affordances: set[str] = set()
    tokens = _tokenize(name)
    if category:
        tokens.update(_tokenize(category))
    for token in tokens:
        for key, affs in _AFFORDANCE_MAP.items():
            if key in token or token in key:
                affordances.update(affs)
    return sorted(affordances)


def _select_target(objects: list[ObjectSpec], candidates: list[str] | None = None) -> str:
    """Pick the most plausible manipulation target from objects."""
    ignore = {"table", "counter", "shelf", "floor", "wall", "background", "scene"}
    for obj in objects:
        name = obj.name.lower()
        if name in ignore:
            continue
        if candidates is None or any(c in name for c in candidates):
            return obj.name
    if objects:
        return objects[0].name
    return "object"


def infer_primitives(
    name: str,
    description: str | None = None,
    success_conditions: list[str] | None = None,
    objects: list[ObjectSpec] | None = None,
) -> list[Primitive]:
    """Infer a list of TDL primitives from task metadata."""
    text = (name or "") + " " + (description or "")
    conditions = success_conditions or []
    for cond in conditions:
        text += " " + cond
    tokens = _tokenize(text)

    primitives: list[Primitive] = []
    objs = objects or []

    # Pick / Lift often appear together; add Pick if we see lift/grasp/take keywords.
    if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Pick"]):
        target = _select_target(objs)
        primitives.append(Primitive(name="Pick", args={"target": target}))
        # If the task also mentions lifting, add Lift for the same object.
        if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Lift"]):
            primitives.append(Primitive(name="Lift", args={"target": target}))

    # Place appears when destination prepositions are present or explicit place verbs.
    place_keywords = set(_PRIMITIVE_KEYWORDS["Place"])
    if any(k in tokens for k in place_keywords):
        target = _select_target(objs)
        # Try to find a destination object (container/surface).
        dest = None
        for obj in objs:
            affs = infer_object_affordances(obj.name, obj.category)
            if "container" in affs or "surface" in affs:
                dest = obj.name
                break
        primitives.append(Primitive(name="Place", args={"target": target, "destination": dest or target}))

    if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Open"]):
        target = _select_target(objs, candidates=["door", "fridge", "cabinet", "drawer", "microwave"])
        primitives.append(Primitive(name="Open", args={"target": target}))

    if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Close"]):
        target = _select_target(objs, candidates=["door", "fridge", "cabinet", "drawer", "microwave"])
        primitives.append(Primitive(name="Close", args={"target": target}))

    if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Press"]):
        target = _select_target(objs, candidates=["button", "switch"])
        primitives.append(Primitive(name="Press", args={"target": target}))

    if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Sort"]):
        primitives.append(Primitive(name="Sort", args={"target": _select_target(objs)}))

    if any(k in tokens for k in _PRIMITIVE_KEYWORDS["Navigate"]):
        primitives.append(Primitive(name="Navigate", args={"target": _select_target(objs)}))

    # Fallback: if no primitive was inferred but there are objects, assume Pick+Place.
    if not primitives and objs:
        target = _select_target(objs)
        primitives.append(Primitive(name="Pick", args={"target": target}))
        primitives.append(Primitive(name="Place", args={"target": target, "destination": target}))

    return primitives


def enrich_objects(objects: list[ObjectSpec]) -> list[ObjectSpec]:
    """Return objects with inferred affordances appended."""
    enriched: list[ObjectSpec] = []
    for obj in objects:
        affs = infer_object_affordances(obj.name, obj.category)
        existing = {str(a) for a in obj.affordances}
        new_affs = [a for a in affs if a not in existing]
        if new_affs:
            obj.affordances.extend(new_affs)
        enriched.append(obj)
    return enriched
