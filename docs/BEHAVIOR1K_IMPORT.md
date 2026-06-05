# BEHAVIOR-1K Semantic Import

## Rationale

BEHAVIOR-1K contains 1000 human-centered household activities with complex physics (liquids, cloth, heat). Full migration to IsaacLab-Arena is out of scope for Phase 1.

Darwin performs **semantic import**:
- activity_name -> Task.name
- BDDL goal -> EvalSpec.success_conditions
- objects -> ObjectSpec
- predicates -> constraints / preconditions / postconditions
- activity category -> domain
- subgoals -> primitives

## Output

All imported tasks are marked:
```yaml
metadata:
  executable: false
  semantic_only: true
```

These tasks serve as:
- Task Genome seeds
- Long-horizon task templates
- Task family hierarchy sources
- Skill requirement maps
