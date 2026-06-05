"""Task composer: chain multiple tasks into composite long-horizon tasks."""

from __future__ import annotations

import copy

from rosclaw_darwin.tdl.schema import EvalSpec, ObjectSpec, Primitive, Task, TaskHorizon


class TaskComposer:
    """Compose multiple tasks into one long-horizon task."""

    def compose(self, tasks: list[Task], name: str | None = None) -> Task:
        if not tasks:
            raise ValueError("compose() requires at least one task")

        all_primitives: list[Primitive] = []
        all_objects: list[ObjectSpec] = []
        all_constraints: list[str] = []
        seen_obj_names: set[str] = set()
        seen_constraints: set[str] = set()

        for t in tasks:
            all_primitives.extend(copy.deepcopy(t.primitives))
            for o in t.objects:
                if o.name not in seen_obj_names:
                    all_objects.append(copy.deepcopy(o))
                    seen_obj_names.add(o.name)
            for c in t.constraints:
                if c not in seen_constraints:
                    all_constraints.append(c)
                    seen_constraints.add(c)

        parent_ids = [t.id for t in tasks]
        id_part = "_".join(t.id for t in tasks)

        # Merge eval specs
        merged_eval = EvalSpec(
            success_conditions=[],
            failure_conditions=[],
            max_steps=sum((t.eval.max_steps or 1000) for t in tasks),
            max_episodes=tasks[0].eval.max_episodes,
        )
        seen_succ: set[str] = set()
        seen_fail: set[str] = set()
        for t in tasks:
            for s in t.eval.success_conditions:
                if s not in seen_succ:
                    merged_eval.success_conditions.append(s)
                    seen_succ.add(s)
            for f in t.eval.failure_conditions:
                if f not in seen_fail:
                    merged_eval.failure_conditions.append(f)
                    seen_fail.add(f)

        return Task(
            id=f"composed_{id_part}",
            name=name or f"Composite: {' + '.join(t.name for t in tasks)}",
            description=f"Auto-composed from {len(tasks)} tasks: {', '.join(t.name for t in tasks)}",
            source="native",
            domain=tasks[0].domain,
            horizon=TaskHorizon.composite,
            scene=copy.deepcopy(tasks[0].scene),
            embodiment=copy.deepcopy(tasks[0].embodiment),
            objects=all_objects,
            primitives=all_primitives,
            constraints=all_constraints,
            eval=merged_eval,
            parents=parent_ids,
            tags=["composed", "long_horizon"],
        )
