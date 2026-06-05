# Task Genome Engine

## Mutators

All mutators inherit from `BaseMutator` and implement `mutate(task, seed) -> Task`.

| Mutator | Effect |
|---------|--------|
| SpatialMutator | Changes object positions and robot initial pose |
| ObjectMutator | Swaps objects with same affordance class |
| DistractorMutator | Adds distractor objects |
| LightingMutator | Changes lighting metadata |
| InstructionMutator | Varies language instruction |
| ConstraintMutator | Adds extra constraints |
| EmbodimentMutator | Swaps robot embodiment |
| HorizonMutator | Expands atomic -> short -> long -> composite |

## Composer

`TaskComposer.compose(tasks)` merges primitives, objects, constraints, and success conditions. Sets `horizon=composite` and `parents=[task_ids]`.

## Failure-Driven Generation

MVP uses a rule table mapping failure types to targeted mutations:
- `handle_grasp_failed` -> vary handle height, orientation, occlusion
- `object_dropped` -> add no_drop constraint, vary surface friction
