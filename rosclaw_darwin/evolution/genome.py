"""Task Genome Engine: task evolution primitives."""

from __future__ import annotations

from rosclaw_darwin.tdl.schema import Task


class TaskGenome:
    """Represent a task as an evolvable genome."""

    @staticmethod
    def copy(task: Task, new_id: str | None = None) -> Task:
        import copy
        t = copy.deepcopy(task)
        if new_id:
            t.id = new_id
        return t
