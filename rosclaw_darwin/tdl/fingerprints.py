"""Task fingerprinting for deduplication and lineage tracking."""

from __future__ import annotations

import hashlib

from .schema import Task


def task_fingerprint(task: Task) -> str:
    """Compute a stable fingerprint for a task based on its structural content."""
    parts: list[str] = [
        task.name,
        task.domain,
        str(task.horizon),
        task.scene.domain or "",
        task.embodiment.robot,
    ]
    for o in sorted(task.objects, key=lambda x: x.name):
        parts.append(f"obj:{o.name}:{o.category or ''}:{','.join(sorted(str(a) for a in o.affordances))}")
    for p in sorted(task.primitives, key=lambda x: x.name):
        parts.append(f"prim:{p.name}:{','.join(sorted(p.args.keys()))}")
    for c in sorted(task.constraints):
        parts.append(f"con:{c}")
    for s in sorted(task.eval.success_conditions):
        parts.append(f"succ:{s}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def primitive_fingerprint(primitive_name: str, affordances: list[str]) -> str:
    """Compute a fingerprint for a skill candidate pattern."""
    parts = [primitive_name] + sorted(affordances)
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
