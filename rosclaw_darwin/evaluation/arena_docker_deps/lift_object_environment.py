# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from isaaclab_arena.assets.register import register_environment
from isaaclab_arena_environments.example_environment_base import ExampleEnvironmentBase

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment


@register_environment
class LiftObjectEnvironment(ExampleEnvironmentBase):

    name: str = "lift_object"

    def get_env(self, args_cli: argparse.Namespace) -> IsaacLabArenaEnvironment:
        import isaaclab_arena_examples.policy.base_rsl_rl_policy as base_rsl_rl_policy
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.lift_object_task import LiftObjectTaskRL
        from isaaclab_arena.utils.pose import Pose
        from isaaclab_arena.assets.object import Object
        from isaaclab_arena.assets.object_base import ObjectType
        import isaaclab.sim as sim_utils

        # Create table as a static BASE asset with explicit box collision.
        # Using ObjectType.BASE avoids IsaacLab's RigidObject kinematic bug in Isaac Sim 5.1.
        table = Object(
            name="table",
            prim_path="{ENV_REGEX_NS}/table",
            object_type=ObjectType.BASE,
            spawner_cfg=sim_utils.CuboidCfg(
                size=(0.8, 1.5, 0.04),
                collision_props=sim_utils.CollisionPropertiesCfg(collision_enabled=True, contact_offset=0.005),
                visible=True,
                physics_material=sim_utils.RigidBodyMaterialCfg(static_friction=0.5, dynamic_friction=0.5),
            ),
            initial_pose=Pose(position_xyz=(0.5, 0, -0.02), rotation_xyzw=(0, 0, 0.707, 0.707)),
        )
        table.object_min_z = -0.05

        pick_up_object = self.asset_registry.get_asset_by_name(args_cli.object)()

        # Add ground plane and light to the scene
        ground_plane = self.asset_registry.get_asset_by_name("ground_plane")()
        light = self.asset_registry.get_asset_by_name("light")()

        assets = [table, pick_up_object, ground_plane, light]

        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(concatenate_observation_terms=True)

        if args_cli.teleop_device is not None:
            teleop_device = self.device_registry.get_device_by_name(args_cli.teleop_device)()
        else:
            teleop_device = None

        # Set all positions
        pick_up_object.set_initial_pose(Pose(position_xyz=(0.5, 0, 0.055), rotation_xyzw=(0, 0, 0, 1)))
        ground_plane.set_initial_pose(Pose(position_xyz=(0.0, 0.0, -1.05)))

        # Compose the scene
        scene = Scene(assets=assets)

        task = LiftObjectTaskRL(
            pick_up_object,
            table,
            embodiment,
            minimum_height_to_lift=0.04,
            episode_length_s=5.0,
            rl_training_mode=args_cli.rl_training_mode,
        )

        isaaclab_arena_environment = IsaacLabArenaEnvironment(
            name=self.name,
            embodiment=embodiment,
            scene=scene,
            task=task,
            teleop_device=teleop_device,
            rl_framework_entry_point="rsl_rl_cfg_entry_point",
            rl_policy_cfg=f"{base_rsl_rl_policy.__name__}:RLPolicyCfg",
        )

        return isaaclab_arena_environment

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--object", type=str, default="dex_cube")
        parser.add_argument("--teleop_device", type=str, default=None)
        parser.add_argument("--embodiment", type=str, default="franka_joint_pos")
        parser.add_argument(
            "--rl_training_mode",
            action="store_true",
            help="Disable success termination (use when training with RSL-RL). Omit for evaluation.",
        )
