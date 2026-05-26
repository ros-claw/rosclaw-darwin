"""Task Genome Engine: generate infinite task variations from a gene pool.

Inspired by RoboCasa's LLM-guided task generation, but fully automated.
The engine maintains a pool of "genes" (primitives, objects, constraints)
and composes them into novel tasks via mutation, crossover, and escalation.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from rosclaw_darwin.tdl.schema import Task, Primitive, Object, Constraint


# Default gene pool — can be extended by the user.
DEFAULT_GENE_POOL: dict[str, list[dict[str, Any]]] = {
    "primitives": [
        {"name": "Pick", "params": {}},
        {"name": "Place", "params": {}},
        {"name": "Push", "params": {}},
        {"name": "Open", "params": {}},
        {"name": "Close", "params": {}},
        {"name": "Navigate", "params": {}},
        {"name": "Observe", "params": {}},
        {"name": "Grasp", "params": {"force": 5.0}},
        {"name": "Rotate", "params": {"angle": 90}},
        {"name": "Pour", "params": {"volume": 0.5}},
    ],
    "objects": [
        {"name": "cup", "object_type": "graspable"},
        {"name": "plate", "object_type": "graspable"},
        {"name": "bottle", "object_type": "container"},
        {"name": "drawer", "object_type": "articulated"},
        {"name": "fridge", "object_type": "articulated"},
        {"name": "table", "object_type": "fixture"},
        {"name": "counter", "object_type": "fixture"},
        {"name": "apple", "object_type": "graspable"},
        {"name": "milk", "object_type": "graspable"},
        {"name": "bowl", "object_type": "container"},
    ],
    "constraints": [
        {"name": "avoid_spill", "constraint_type": "safety", "weight": 2.0},
        {"name": "upright_placement", "constraint_type": "physical", "weight": 1.0},
        {"name": "no_collision", "constraint_type": "safety", "weight": 1.5},
        {"name": "within_reach", "constraint_type": "physical", "weight": 1.0},
        {"name": "gentle_force", "constraint_type": "safety", "weight": 1.0},
    ],
}


class TaskGenomeEngine:
    """Generate task variations using genetic-programming-style operations."""

    def __init__(self, gene_pool: dict[str, list[dict[str, Any]]] | None = None):
        self.gene_pool = gene_pool or DEFAULT_GENE_POOL
        self._history: list[str] = []  # Track generated task IDs for lineage.

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mutate(self, task: Task, n_variations: int = 1) -> list[Task]:
        """Produce task variants by randomly mutating primitives/objects/constraints."""
        variants: list[Task] = []
        for i in range(n_variations):
            t = copy.deepcopy(task)
            t.parent_id = task.id
            t.id = f"{task.id}_mut_{i}"
            t.name = f"{task.name} (mutated {i})"
            t.difficulty = min(task.difficulty + 0.5, 10.0)

            op = random.choice(["add_primitive", "swap_object", "add_constraint", "escalate"])
            if op == "add_primitive":
                self._add_primitive(t)
            elif op == "swap_object":
                self._swap_object(t)
            elif op == "add_constraint":
                self._add_constraint(t)
            elif op == "escalate":
                self._escalate(t)

            variants.append(t)
            self._history.append(t.id)
        return variants

    def compose(self, tasks: list[Task]) -> Task:
        """Chain multiple tasks into one composite long-horizon task."""
        if not tasks:
            raise ValueError("compose() requires at least one task")

        all_primitives: list[Primitive] = []
        all_objects: list[Object] = []
        all_constraints: list[Constraint] = []
        seen_obj_names: set[str] = set()
        seen_con_names: set[str] = set()

        for t in tasks:
            all_primitives.extend(t.primitives)
            for o in t.objects:
                if o.name not in seen_obj_names:
                    all_objects.append(o)
                    seen_obj_names.add(o.name)
            for c in t.constraints:
                if c.name not in seen_con_names:
                    all_constraints.append(c)
                    seen_con_names.add(c.name)

        parent_ids = "+".join(t.id for t in tasks)
        return Task(
            id=f"composed_{parent_ids}",
            name=f"Composite: {' + '.join(t.name for t in tasks)}",
            source="rosclaw-tdl",
            description=f"Auto-composed from {len(tasks)} tasks",
            primitives=all_primitives,
            objects=all_objects,
            constraints=all_constraints,
            difficulty=min(sum(t.difficulty for t in tasks), 10.0),
            parent_id=parent_ids,
            tags=["composed", "long_horizon"],
        )

    def generate_random(self, n_tasks: int = 1, max_primitives: int = 5) -> list[Task]:
        """Generate entirely new tasks by sampling from the gene pool."""
        tasks: list[Task] = []
        for i in range(n_tasks):
            n_prim = random.randint(1, max_primitives)
            primitives = [
                Primitive(**random.choice(self.gene_pool["primitives"]))
                for _ in range(n_prim)
            ]
            # Attach targets to primitives by sampling objects
            obj_sample = random.sample(self.gene_pool["objects"], k=min(3, len(self.gene_pool["objects"])))
            objects = [Object(**o) for o in obj_sample]
            for p in primitives:
                if p.target is None and objects:
                    p.target = random.choice(objects).name

            constraints = [
                Constraint(**random.choice(self.gene_pool["constraints"]))
                for _ in range(random.randint(0, 2))
            ]

            task = Task(
                id=f"genome_rand_{i}_{random.randint(1000, 9999)}",
                name=f"Generated Task {i}",
                source="rosclaw-tdl",
                description="Auto-generated from gene pool",
                primitives=primitives,
                objects=objects,
                constraints=constraints,
                difficulty=random.uniform(1.0, 5.0),
                tags=["generated"],
            )
            tasks.append(task)
            self._history.append(task.id)
        return tasks

    # ------------------------------------------------------------------
    # Internal mutation operators
    # ------------------------------------------------------------------

    def _add_primitive(self, task: Task) -> None:
        gene = random.choice(self.gene_pool["primitives"])
        p = Primitive(**gene)
        if task.objects:
            p.target = random.choice(task.objects).name
        task.primitives.append(p)

    def _swap_object(self, task: Task) -> None:
        if not task.objects:
            return
        idx = random.randrange(len(task.objects))
        gene = random.choice(self.gene_pool["objects"])
        task.objects[idx] = Object(**gene)

    def _add_constraint(self, task: Task) -> None:
        gene = random.choice(self.gene_pool["constraints"])
        task.constraints.append(Constraint(**gene))

    def _escalate(self, task: Task) -> None:
        """Increase difficulty: add more primitives, stricter constraints."""
        self._add_primitive(task)
        self._add_constraint(task)
        task.difficulty = min(task.difficulty + 1.0, 10.0)
