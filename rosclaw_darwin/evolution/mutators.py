"""Task mutators: generate variations of tasks."""

from __future__ import annotations

import copy
import random

from rosclaw_darwin.tdl.schema import ObjectSpec, Primitive, Task, TaskHorizon


class BaseMutator:
    name: str = "base"

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        raise NotImplementedError


class SpatialMutator(BaseMutator):
    name = "spatial"

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        for o in t.objects:
            if "position" not in o.metadata:
                o.metadata["position"] = {"x": 0.0, "y": 0.0, "z": 0.0}
            o.metadata["position"]["x"] += rng.uniform(-0.2, 0.2)
            o.metadata["position"]["y"] += rng.uniform(-0.2, 0.2)
        # Mutate robot initial pose
        if t.embodiment.metadata.get("initial_pose"):
            t.embodiment.metadata["initial_pose"]["x"] += rng.uniform(-0.1, 0.1)
            t.embodiment.metadata["initial_pose"]["y"] += rng.uniform(-0.1, 0.1)
        return t


class ObjectMutator(BaseMutator):
    name = "object"

    _SWAPS: dict[str, list[str]] = {
        "milk": ["bottle", "can", "carton", "juice_box"],
        "bottle": ["milk", "can", "jar"],
        "drawer": ["cabinet", "microwave", "oven"],
        "fridge": ["cabinet", "pantry", "drawer"],
        "table": ["counter", "desk", "shelf"],
        "cup": ["mug", "glass", "bowl"],
        "bowl": ["plate", "cup", "container"],
    }

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        for o in t.objects:
            candidates = self._SWAPS.get(o.name, [])
            if candidates and rng.random() < 0.5:
                o.name = rng.choice(candidates)
                o.native_ref = None
        return t


class DistractorMutator(BaseMutator):
    name = "distractor"

    _DISTRACTORS: list[str] = ["pen", "book", "remote", "phone", "key", "spoon"]

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        n_distractors = rng.randint(1, 3)
        for _ in range(n_distractors):
            name = rng.choice(self._DISTRACTORS)
            t.objects.append(ObjectSpec(
                name=f"{name}_distractor_{rng.randint(1, 99)}",
                category="distractor",
                affordances=["graspable", "movable"],
            ))
        return t


class LightingMutator(BaseMutator):
    name = "lighting"

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        t.metadata["lighting"] = {
            "intensity": rng.uniform(0.5, 1.5),
            "temperature": rng.uniform(3000, 6500),
        }
        return t


class InstructionMutator(BaseMutator):
    name = "instruction"

    _VARIANTS: dict[str, list[str]] = {
        "take milk": [
            "bring me the milk from the fridge",
            "get the milk carton",
            "retrieve the milk bottle",
        ],
        "open fridge": [
            "open the refrigerator door",
            "access the fridge",
            "pull open the fridge",
        ],
        "place object": [
            "put the item on the table",
            "set down the object",
            "drop the item at the target",
        ],
    }

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        desc_lower = (t.description or "").lower()
        for key, variants in self._VARIANTS.items():
            if key in desc_lower:
                t.description = rng.choice(variants)
                break
        else:
            # Generic expansion
            if t.description:
                t.description = f"Please {t.description.lower()}"
        return t


class ConstraintMutator(BaseMutator):
    name = "constraint"

    _EXTRA: list[str] = [
        "collision_free",
        "time_limit",
        "no_drop",
        "close_after_open",
        "upright_placement",
    ]

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        new_constraint = rng.choice(self._EXTRA)
        if new_constraint not in t.constraints:
            t.constraints.append(new_constraint)
        return t


class EmbodimentMutator(BaseMutator):
    name = "embodiment"

    _SWAPS: list[list[str]] = [
        ["franka", "unitree_g1", "gr1"],
        ["unitree_g1", "gr1", "franka"],
        ["so100", "franka"],
    ]

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        current = t.embodiment.robot
        for group in self._SWAPS:
            if current in group:
                others = [r for r in group if r != current]
                if others:
                    t.embodiment.robot = rng.choice(others)
                    break
        return t


class HorizonMutator(BaseMutator):
    name = "horizon"

    def mutate(self, task: Task, seed: int | None = None) -> Task:
        rng = random.Random(seed)
        t = copy.deepcopy(task)
        order = [TaskHorizon.atomic, TaskHorizon.short, TaskHorizon.long, TaskHorizon.composite]
        current_idx = order.index(TaskHorizon(task.horizon)) if task.horizon in {h.value for h in order} else 0
        if current_idx < len(order) - 1 and rng.random() < 0.7:
            t.horizon = order[current_idx + 1]
            # Add a chained primitive
            if t.primitives:
                last = t.primitives[-1]
                chain_map = {
                    "grasp": "place",
                    "pick": "place",
                    "open": "grasp",
                    "navigate_to": "grasp",
                }
                next_name = chain_map.get(last.name)
                if next_name:
                    t.primitives.append(Primitive(name=next_name, args={"target": "target"}))
        return t


MUTATOR_REGISTRY: dict[str, type[BaseMutator]] = {
    "spatial": SpatialMutator,
    "object": ObjectMutator,
    "distractor": DistractorMutator,
    "lighting": LightingMutator,
    "instruction": InstructionMutator,
    "constraint": ConstraintMutator,
    "embodiment": EmbodimentMutator,
    "horizon": HorizonMutator,
}
