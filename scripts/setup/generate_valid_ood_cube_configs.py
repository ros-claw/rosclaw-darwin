#!/usr/bin/env python3
"""Generate ROSClaw-validated OOD cube task configs.

The resulting configs use Arena's ``procedural_cube`` object key (so no USD
asset is required) but mark the task with ``rosclaw_valid_cube: true`` so the
container-side patch in ``run_eval.py`` forces collision geometry on.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rosclaw_darwin.evaluation.arena_docker_deps.validated_objects import (
    VALIDATED_CUBE_VARIANTS,
)

_TEMPLATE = """id: {task_id}
name: Goal Pose ROSClaw Valid Cube {variant_name}
version: "1.0"
description: goal_pose with a rosclaw-validated procedural_cube variant ({variant_desc}).
source: native
domain: manipulation
horizon: atomic
scene:
  name: table_simple
  domain: table
primitives:
  - name: Orient
    args:
      target: cube
objects:
  - name: cube
    category: graspable
    affordances: [graspable]
embodiment:
  robot: franka
  control_mode: ik
constraints: []
eval:
  max_steps: 300
  max_episodes: 5
  success_conditions: [pose_reached]
  metrics: [success_rate, completion_time]
mutation:
  allowed: [spatial, object, constraint]
  difficulty: 1
  seed: 42
tags: [table, atomic, pose, rosclaw_valid_ood]
metadata:
  difficulty: 1.0
  benchmark_scope: rosclaw_ood_diagnostic
  official_asset: false
  can_claim_official_benchmark: false
  requires_object_validity: true
  arena_env_args:
    environment: cube_goal_pose
    object: procedural_cube
    embodiment: franka_ik_abs
  physics_ablation:
{physics_ablation_yaml}
"""


def _to_yaml_block(d: dict, indent: int = 4) -> str:
    lines = []
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{' ' * indent}{k}:")
            for item in v:
                lines.append(f"{' ' * (indent + 2)}- {item}")
        elif isinstance(v, dict):
            lines.append(f"{' ' * indent}{k}:")
            lines.append(_to_yaml_block(v, indent + 2))
        else:
            lines.append(f"{' ' * indent}{k}: {v}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate valid OOD cube task configs")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("configs/tasks"),
    )
    args = parser.parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for variant, spec in VALIDATED_CUBE_VARIANTS.items():
        task_id = f"goal_pose_rosclaw_valid_cube_{variant.replace('valid_cube_', '')}"
        physics_ablation = spec.to_physics_ablation()
        content = _TEMPLATE.format(
            task_id=task_id,
            variant_name=spec.name,
            variant_desc=f"size={spec.size[0]:.3f} m, mass={spec.mass:.3f} kg",
            physics_ablation_yaml=_to_yaml_block(physics_ablation),
        )
        (out_dir / f"{task_id}.yaml").write_text(content, encoding="utf-8")
        print(f"Wrote {out_dir / f'{task_id}.yaml'}")


if __name__ == "__main__":
    main()
