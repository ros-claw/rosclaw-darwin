"""IsaacLab-Arena environment adapter.

Wraps Arena's composable Scene + Embodiment + Task primitives.
When IsaacLab-Arena is not installed, falls back to a mock mode for
unit tests and development.
"""

from __future__ import annotations


def _patch_warp_to_torch() -> None:
    """Monkey-patch Warp to_torch so it accepts PyTorch tensors (Arena sometimes passes tensors to wp.to_torch)."""
    try:
        import torch
        import warp

        _orig = warp.to_torch

        def _patched(a, requires_grad=None):
            if isinstance(a, torch.Tensor):
                return a
            return _orig(a, requires_grad)

        warp.to_torch = _patched
    except Exception:
        pass

import argparse
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.policy_metadata import load_policy_metadata
from rosclaw_darwin.evaluation.result import ClaimLevel, EvaluationResult, MetricScope
from rosclaw_darwin.tdl.schema import Task

from .base import BaseEnvironmentAdapter


def _map_task_to_arena_env(task: Task, robot: str) -> dict[str, Any] | None:
    """Use the capability registry to map a Task to Arena environment args.

    Falls back to the legacy hard-coded mapper if the registry match is too weak.
    """
    from rosclaw_darwin.arena_bridge.task_matcher import TaskArenaMatcher

    matcher = TaskArenaMatcher()
    best = matcher.best_match(task, threshold=0.5)
    if best is not None and best.executable:
        args = matcher.build_arena_args(task)
        if args is not None:
            return args
    return None


def _patch_procedural_contact_sensor(obj: Any) -> None:
    """Monkey-patch get_contact_sensor_cfg for procedural objects.

    Procedural objects have ``usd_path=""`` so the base implementation
    (which opens the USD stage to find the shallowest rigid body) fails.
    For a procedural cube the rigid body lives directly at ``obj.prim_path``,
    so we can return a sensor config pointing there.
    """
    from isaaclab.sensors import ContactSensorCfg

    def _patched(contact_against_object: Any | None = None, usd_path: str | None = None) -> ContactSensorCfg:
        # For procedural objects the sensor prim path is the object's prim path.
        return ContactSensorCfg(
            prim_path=obj.prim_path,
            filter_prim_paths_expr=[contact_against_object.prim_path] if contact_against_object else [],
        )

    obj.get_contact_sensor_cfg = _patched


class _ArenaComponentMapper:
    """Maps ROSClaw Task definitions to IsaacLab-Arena components.

    ROSClaw tasks use high-level primitives (Navigate, Pick, Place, Open,
    Close) and abstract object names (milk_carton, fridge). Arena expects
    concrete Asset objects, Embodiment instances, and TaskBase subclasses.
    """

    # Map ROSClaw object names → Arena asset registry names.
    # These names must match the ``name`` attribute of a registered asset.
    # Only names present in the local Arena asset registry are listed; using
    # unregistered names causes the example environment to fail during asset
    # lookup.
    _OBJECT_MAP: dict[str, str] = {
        # YCB / HOT3D / local assets that are registered in Arena.
        "milk_carton": "milk_carton_hot3d_robolab",
        "cracker_box": "cracker_box",
        "mustard_bottle": "mustard_bottle",
        "sugar_box": "sugar_box",
        "tomato_soup_can": "tomato_soup_can",
        "power_drill": "power_drill",
        "microwave": "microwave",
        "coffee_machine": "coffee_machine",
        "mug": "mug",
        "bowl": "bowl_ycb_robolab",
        "banana": "banana_ycb_robolab",
        "brick": "brick_ycb_robolab",
        "plate": "wooden_bowl_hot3d_robolab",
        "cup": "mug",
        "bottle": "beer_bottle",
        "can": "soup_can_hot3d_robolab",
        "box": "brown_box",
        "cube": "dex_cube",
        "sphere": "sphere",
        "bin": "blue_sorting_bin",
        "container": "red_container",
        # Procedural fallback assets (no Nucleus required).
        "procedural_cube": "procedural_cube",
    }

    # Arena assets that have explicit local USD paths (not Lightwheel cloud).
    # The Docker runtime patches Lightwheel to a dummy USD, so cloud-backed
    # assets fail to spawn. Use this set to fall back to local geometry.
    _LOCAL_ARENA_OBJECTS: frozenset[str] = frozenset({
        "cracker_box",
        "mustard_bottle",
        "sugar_box",
        "tomato_soup_can",
        "power_drill",
        "mug",
        "dex_cube",
        "brown_box",
        "sphere",
        "blue_sorting_bin",
        "red_container",
        "green_container",
        "red_cube",
        "green_cube",
        "banana_ycb_robolab",
        "bowl_ycb_robolab",
        "brick_ycb_robolab",
        "milk_carton_hot3d_robolab",
        "wooden_bowl_hot3d_robolab",
        "soup_can_hot3d_robolab",
        "table_maple_robolab",
        "procedural_table",
        "procedural_cube",
    })

    # Map ROSClaw scene names → Arena background asset names.
    # Nucleus-backed assets (require Omniverse connection) are listed first;
    # the adapter falls back to "procedural_table" when Nucleus is unavailable.
    _SCENE_MAP: dict[str, str] = {
        "kitchen_modern_01": "kitchen",
        "kitchen": "kitchen",
        "table_simple": "table",
        "table": "table",
        "packing_table": "packing_table",
        "galileo": "galileo",
        "robolab": "maple_table_robolab",
        "default": "procedural_table",
    }

    # Map ROSClaw robot names → Arena embodiment registry names.
    _ROBOT_MAP: dict[str, str] = {
        "franka": "franka_ik",
        "franka_ik": "franka_ik",
        "franka_ik_abs": "franka_ik_abs",
        "franka_joint": "franka_joint",
        "franka_joint_pos": "franka_joint_pos",
        "kuka_allegro": "kuka_allegro",
    }

    def __init__(self, task: Task):
        self.task = task

    def build_arena_components(self):
        """Return (scene, task, embodiment) for IsaacLabArenaEnvironment."""
        from isaaclab_arena.assets.registries import AssetRegistry
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.utils.pose import Pose

        registry = AssetRegistry()

        # --- Background ---
        # Try the mapped scene name first; fall back to procedural_table
        # when Nucleus USD assets are not available.
        bg_name = self._SCENE_MAP.get((self.task.scene.name or self.task.scene.domain or 'default'), "procedural_table")
        try:
            background = registry.get_asset_by_name(bg_name)()
        except (KeyError, ValueError, Exception):
            background = registry.get_asset_by_name("procedural_table")()

        # Patch object_min_z so objects have time to settle before triggering
        # object_dropped (default 0.0 causes immediate failure on penetration).
        if hasattr(background, "object_min_z"):
            background.object_min_z = -0.2

        # --- Lighting ---
        try:
            light = registry.get_asset_by_name("light")()
        except (KeyError, ValueError, Exception):
            light = None

        # --- Objects ---
        # All objects are created as procedural cubes when Nucleus is
        # unavailable. This avoids USD loading errors while still giving
        # the robot something to manipulate.
        arena_objects: list[Any] = []
        _procedural_cls = registry.get_asset_by_name("procedural_cube")

        # Enable contact sensors on the procedural cube spawn config so
        # PickAndPlaceTask can create contact sensors on these objects.
        # Also support diagnostic physics ablation (friction / size / mass).
        physics_ablation = dict(self.task.metadata.get("physics_ablation") or {})

        if hasattr(_procedural_cls, "_generate_rigid_cfg"):
            _orig_generate = _procedural_cls._generate_rigid_cfg

            def _patched_generate(self):
                cfg = _orig_generate(self)
                if hasattr(cfg, "spawn") and cfg.spawn is not None:
                    cfg.spawn.activate_contact_sensors = True
                    variant = getattr(self, "_physics_variant", {})
                    if variant.get("static_friction") is not None and hasattr(cfg.spawn, "physics_material"):
                        cfg.spawn.physics_material.static_friction = variant["static_friction"]
                        cfg.spawn.physics_material.dynamic_friction = variant.get("dynamic_friction", variant["static_friction"])
                    if variant.get("size") is not None and hasattr(cfg.spawn, "size"):
                        cfg.spawn.size = variant["size"]
                    if variant.get("mass") is not None and hasattr(cfg.spawn, "mass_props"):
                        cfg.spawn.mass_props.mass = variant["mass"]
                return cfg

            _procedural_cls._generate_rigid_cfg = _patched_generate

        # Place objects closer to the robot's initial reach (x~0.45) so the
        # end-effector doesn't need to travel far horizontally.
        for idx, obj in enumerate(self.task.objects):
            # Each object needs a unique prim path to avoid USD stage collisions.
            prim_path = f"{{ENV_REGEX_NS}}/{obj.name}"
            inst = _procedural_cls(instance_name=obj.name, prim_path=prim_path)
            inst._physics_variant = physics_ablation
            # z=0.07 places object bottom at table top (z=0.02) for procedural cube
            # with half-height 0.05. Previous z=0.05 caused object to spawn inside table.
            inst.set_initial_pose(Pose(position_xyz=(0.35 + idx * 0.05, 0.0, 0.07)))
            arena_objects.append(inst)

        # If no objects were mapped at all, add a procedural cube so that
        # manipulation tasks have something to interact with.
        if not arena_objects:
            inst = _procedural_cls(instance_name="object", prim_path="{ENV_REGEX_NS}/object")
            inst._physics_variant = physics_ablation
            from isaaclab_arena.utils.pose import Pose
            inst.set_initial_pose(Pose(position_xyz=(0.35, 0.0, 0.07)))
            arena_objects.append(inst)

        # Procedural objects have empty usd_path; tasks like PickAndPlace
        # call get_contact_sensor_cfg which tries to open the USD stage.
        # Monkey-patch a simplified version that works for procedural cubes.
        for obj in arena_objects:
            if getattr(obj, "usd_path", None) == "":
                _patch_procedural_contact_sensor(obj)

        # --- Scene ---
        scene_assets: list[Any] = [background]
        if light is not None:
            scene_assets.append(light)
        scene_assets.extend(arena_objects)
        scene = Scene(assets=scene_assets)

        # --- Embodiment ---
        embodiment = self._create_embodiment()

        # --- Task ---
        arena_task = self._create_task(registry, arena_objects, background)

        return scene, arena_task, embodiment

    def _create_embodiment(self):
        """Create an Arena Embodiment from the robot field or metadata override."""
        from isaaclab_arena.embodiments.franka.franka import FrankaIKEmbodiment
        from isaaclab_arena.embodiments.kuka_allegro.kuka_allegro import KukaAllegroEmbodiment

        # Allow task metadata to override the embodiment selection.
        override = (self.task.metadata.get("arena_env_args") or {}).get("embodiment")
        robot = override or self._ROBOT_MAP.get(self.robot, "franka_ik")

        if robot == "franka_ik":
            embodiment = FrankaIKEmbodiment()
            # Use IsaacLab lift-cube initial pose (elbow bent lower) instead of
            # Arena's default upright pose, so the end-effector starts closer to
            # tabletop objects (~z=0.5 instead of ~z=0.84).
            embodiment.set_initial_joint_pose(
                [0.0, -0.569, 0.0, -2.81, 0.0, 3.037, 0.741, 0.04, 0.04]
            )
            # Disable joint randomization for deterministic reset behaviour
            # (random offsets cause unpredictable workspace changes).
            if hasattr(embodiment, "event_config") and hasattr(
                embodiment.event_config, "randomize_franka_joint_state"
            ):
                embodiment.event_config.randomize_franka_joint_state.params["std"] = 0.0
            # Switch to ABSOLUTE pose mode for direct position control
            # (relative mode causes unpredictable cross-axis coupling).
            if hasattr(embodiment, "action_config") and hasattr(
                embodiment.action_config, "arm_action"
            ):
                arm_action_cfg = embodiment.action_config.arm_action
                print(f"[ARENA_ADAPTER] before replace: use_relative_mode={getattr(getattr(arm_action_cfg, 'controller', None), 'use_relative_mode', None)}, scale={getattr(arm_action_cfg, 'scale', None)}", flush=True)
                if hasattr(arm_action_cfg, "controller"):
                    new_controller = arm_action_cfg.controller.replace(
                        use_relative_mode=False
                    )
                    arm_action_cfg = arm_action_cfg.replace(
                        controller=new_controller,
                        scale=1.0,
                    )
                    embodiment.action_config.arm_action = arm_action_cfg
                print(f"[ARENA_ADAPTER] after replace: use_relative_mode={getattr(getattr(embodiment.action_config.arm_action, 'controller', None), 'use_relative_mode', None)}, scale={getattr(embodiment.action_config.arm_action, 'scale', None)}", flush=True)
            return embodiment
        if robot == "franka_joint_pos":
            from isaaclab_arena.embodiments.franka.franka import FrankaJointPosEmbodiment

            embodiment = FrankaJointPosEmbodiment()
            # Use the same tabletop-friendly initial pose as the IK embodiment.
            embodiment.set_initial_joint_pose(
                [0.0, -0.569, 0.0, -2.81, 0.0, 3.037, 0.741, 0.04, 0.04]
            )
            # Disable joint randomization for deterministic calibration.
            if hasattr(embodiment, "event_config") and hasattr(
                embodiment.event_config, "randomize_franka_joint_state"
            ):
                embodiment.event_config.randomize_franka_joint_state.params["std"] = 0.0
            return embodiment
        if robot == "franka_joint":
            from isaaclab_arena.embodiments.franka.franka import FrankaJointEmbodiment

            return FrankaJointEmbodiment()
        if robot == "kuka_allegro":
            return KukaAllegroEmbodiment()
        return FrankaIKEmbodiment()

    def _create_task(self, registry, arena_objects, background):
        """Derive an Arena TaskBase from ROSClaw primitives."""
        primitives = [p.name for p in self.task.primitives]

        # --- Pick + Place ---
        if "Pick" in primitives and "Place" in primitives:
            return self._make_pick_and_place_task(registry, arena_objects, background)

        # --- Lift ---
        if "Lift" in primitives:
            return self._make_lift_task(registry, arena_objects, background)

        # --- Goal Pose (reorientation) ---
        if any("orient" in p.lower() or "rotate" in p.lower() for p in primitives):
            return self._make_goal_pose_task(registry, arena_objects, background)

        # --- Open / Close ---
        if "Open" in primitives:
            return self._make_open_task(registry, arena_objects, background)
        if "Close" in primitives:
            return self._make_close_task(registry, arena_objects, background)

        # --- Press / Button ---
        if "Press" in primitives:
            return self._make_press_button_task(registry, arena_objects, background)

        # --- Sorting ---
        if "Sort" in primitives:
            return self._make_sorting_task(registry, arena_objects, background)

        # Fallback: use the first object as a simple goal-pose task.
        if arena_objects:
            return self._make_goal_pose_task(registry, arena_objects, background)

        # Ultimate fallback: no-op task.
        from isaaclab_arena.tasks.no_task import NoTask
        return NoTask()

    # ------------------------------------------------------------------
    # Task factories
    # ------------------------------------------------------------------

    def _make_pick_and_place_task(self, registry, arena_objects, background):
        """Build a PickAndPlaceTask from ROSClaw primitives."""
        from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
        from isaaclab_arena.utils.pose import Pose

        pick_obj = self._resolve_primitive_target("Pick", registry, arena_objects)
        place_obj = self._resolve_primitive_target("Place", registry, arena_objects)

        if pick_obj is None:
            if arena_objects:
                pick_obj = arena_objects[0]
            else:
                pick_obj = registry.get_asset_by_name("procedural_cube")()

        if place_obj is None:
            # Try to find a fridge/container-like object in arena_objects as destination
            for obj in arena_objects:
                obj_name = getattr(obj, "name", "")
                if obj_name in ("fridge", "container", "bin"):
                    place_obj = obj
                    break
        if place_obj is None:
            # Default destination: the background surface.
            place_obj = background

        # Set sensible initial poses if not already set.
        if hasattr(pick_obj, "set_initial_pose") and pick_obj.initial_pose is None:
            pick_obj.set_initial_pose(Pose(position_xyz=(0.35, 0.0, 0.05)))

        return PickAndPlaceTask(
            pick_up_object=pick_obj,
            destination_location=place_obj,
            background_scene=background,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    def _make_lift_task(self, registry, arena_objects, background):
        """Build a LiftObjectTask."""
        from isaaclab_arena.tasks.lift_object_task import LiftObjectTask
        from isaaclab_arena.utils.pose import Pose

        lift_obj = self._resolve_primitive_target("Lift", registry, arena_objects)
        if lift_obj is None:
            lift_obj = arena_objects[0] if arena_objects else registry.get_asset_by_name("procedural_cube")()

        if hasattr(lift_obj, "set_initial_pose") and lift_obj.initial_pose is None:
            lift_obj.set_initial_pose(Pose(position_xyz=(0.1, 0.0, 0.05)))

        return LiftObjectTask(
            lift_object=lift_obj,
            background_scene=background,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    def _make_goal_pose_task(self, registry, arena_objects, background):
        """Build a GoalPoseTask (reorientation)."""
        from isaaclab_arena.tasks.goal_pose_task import GoalPoseTask
        from isaaclab_arena.utils.pose import Pose

        target = arena_objects[0] if arena_objects else registry.get_asset_by_name("procedural_cube")()
        if hasattr(target, "set_initial_pose") and target.initial_pose is None:
            target.set_initial_pose(Pose(position_xyz=(0.1, 0.0, 0.05)))

        return GoalPoseTask(
            object=target,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    def _make_open_task(self, registry, arena_objects, background):
        """Build an OpenDoorTask."""
        from isaaclab_arena.tasks.open_door_task import OpenDoorTask

        target = self._resolve_primitive_target("Open", registry, arena_objects)
        if target is None:
            target = arena_objects[0] if arena_objects else background
        return OpenDoorTask(
            door=target,
            background_scene=background,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    def _make_close_task(self, registry, arena_objects, background):
        """Build a CloseDoorTask."""
        from isaaclab_arena.tasks.close_door_task import CloseDoorTask

        target = self._resolve_primitive_target("Close", registry, arena_objects)
        if target is None:
            target = arena_objects[0] if arena_objects else background
        return CloseDoorTask(
            door=target,
            background_scene=background,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    def _make_press_button_task(self, registry, arena_objects, background):
        """Build a PressButtonTask."""
        from isaaclab_arena.tasks.press_button_task import PressButtonTask

        target = self._resolve_primitive_target("Press", registry, arena_objects)
        if target is None:
            target = arena_objects[0] if arena_objects else background
        return PressButtonTask(
            pressable_object=target,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    def _make_sorting_task(self, registry, arena_objects, background):
        """Build a SortingTask."""
        from isaaclab_arena.tasks.sorting_task import SortingTask

        if len(arena_objects) < 2:
            # Not enough objects for sorting; fall back to pick-and-place.
            return self._make_pick_and_place_task(registry, arena_objects, background)

        return SortingTask(
            objects_to_sort=arena_objects,
            background_scene=background,
            episode_length_s=(self.task.eval.max_steps or 1000) * 0.05,
            task_description=self.task.description or None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_primitive_target(self, primitive_name: str, registry, arena_objects):
        """Find the Arena object associated with a primitive's target."""
        for p in self.task.primitives:
            if p.name == primitive_name and p.args.get('target'):
                # First try arena_objects list (already mapped).
                for obj in arena_objects:
                    if getattr(obj, "name", None) == p.args.get('target'):
                        return obj
                    # Also check against the mapped name.
                    mapped = self._OBJECT_MAP.get(p.args.get('target'), p.args.get('target'))
                    if getattr(obj, "name", None) == mapped:
                        return obj
                # Not found in arena_objects: try registry directly.
                try:
                    mapped = self._OBJECT_MAP.get(p.args.get('target'), p.args.get('target'))
                    return registry.get_asset_by_name(mapped)()
                except (KeyError, ValueError, AssertionError, Exception):
                    pass
        return None

    @property
    def robot(self) -> str:
        return getattr(self.task, "robot", "franka")


class ArenaAdapter(BaseEnvironmentAdapter):
    """Adapter for NVIDIA IsaacLab-Arena simulator.

    Supports three modes:
      1. **mock** (default): No GPU required, for development/CI.
      2. **real**: Direct import in a Kit-enabled Python process.
      3. **docker**: Runs inside Docker container with full Isaac Sim.

    The mode is auto-selected based on availability:
      - If `isaaclab_arena` is importable -> real mode.
      - If `ROSCLAW_ARENA_MODE` env var is "docker" -> docker mode.
      - Otherwise -> mock mode.
    """

    name = "isaaclab-arena"

    def __init__(
        self,
        task: Task,
        robot: str = "franka",
        headless: bool = True,
        mode: str | None = None,
        num_envs: int = 1,
        device: str = "cuda:0",
        **kwargs: Any,
    ):
        super().__init__(task, **kwargs)
        self.robot = robot
        self.headless = headless
        self._explicit_mode = mode is not None
        self._mode = mode or self._detect_mode()
        self._step_count = 0
        self._simulation_app: Any | None = None
        self._num_envs = num_envs
        self._device = device

    @staticmethod
    def _detect_mode() -> str:
        import os
        import subprocess

        mode = os.environ.get("ROSCLAW_ARENA_MODE", "")
        if mode == "docker":
            return "docker"
        if mode == "mock":
            return "mock"

        try:
            import isaaclab_arena  # noqa: F401
            return "real"
        except ImportError:
            pass

        # Auto-detect Docker mode if arena-base image exists
        try:
            result = subprocess.run(
                ["docker", "images", "-q", "rosclaw-darwin:arena-base"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "docker"
        except Exception:
            pass

        return "mock"

    def build(self) -> None:
        if self._mode == "real":
            self._build_real()
        elif self._mode == "docker":
            self._build_docker()
        else:
            self._build_mock()

    def _build_real(self) -> None:
        """Build using real IsaacLab-Arena APIs."""
        # Patch Franka USD path before ArenaEnvBuilder imports the module.
        # Arena's custom franka_panda_hand_on_stand.usd is not available locally;
        # fall back to the standard IsaacLab panda_instanceable.usd.
        try:
            import isaaclab_arena.embodiments.franka.franka as _franka_mod
            _local_franka = "/data/omniverse/Assets/Isaac/6.0/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd"
            if hasattr(_franka_mod, "_FRANKA_IK_REL_CFG"):
                _franka_mod._FRANKA_IK_REL_CFG.spawn.usd_path = _local_franka
            if hasattr(_franka_mod, "_FRANKA_JOINT_POS_CFG"):
                _franka_mod._FRANKA_JOINT_POS_CFG.spawn.usd_path = _local_franka
        except Exception:
            pass

        from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

        # Map ROSClaw task to Arena components.
        mapper = _ArenaComponentMapper(self.task)
        scene, arena_task, embodiment = mapper.build_arena_components()

        # Create the Arena environment descriptor.
        arena_env = IsaacLabArenaEnvironment(
            name=self.task.id,
            scene=scene,
            embodiment=embodiment,
            task=arena_task,
        )

        # Build args Namespace (avoids CLI parsing conflicts with Kit).
        args = self._make_args()

        builder = ArenaEnvBuilder(arena_env, args)
        self._env = builder.make_registered()

    def _build_docker(self) -> None:
        """Build inside Docker container with Isaac Sim."""
        if self._simulation_app is None:
            try:
                from isaacsim.simulation_app import SimulationApp

                self._simulation_app = SimulationApp(
                    {
                        "headless": self.headless,
                        "width": 1280,
                        "height": 720,
                        "--/persistent/isaac/asset_root/default": "/data/omniverse/Assets/Isaac/6.0",
                        "--/persistent/isaac/asset_root/cloud": "/data/omniverse/Assets/Isaac/6.0",
                    }
                )
            except ImportError as e:
                raise RuntimeError(
                    "IsaacSim SimulationApp not available. "
                    "Ensure the container is based on nvcr.io/nvidia/isaac-sim."
                ) from e

        # Warp is now initialized; apply runtime patches
        _patch_warp_to_torch()

        self._patch_arena_compatibility()

        # Ensure Arena-specific robot assets point to local equivalents.
        # IsaacLab-Arena uses a custom franka_panda_hand_on_stand.usd that
        # is not available in the local asset tree; symlink it to the
        # standard panda_instanceable.usd so the embodiment loads.
        import os
        _arena_robot_dir = "/data/omniverse/Assets/Isaac/6.0/Isaac/IsaacLab/Arena/assets/robot_library"
        _local_franka = "/data/omniverse/Assets/Isaac/6.0/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd"
        _arena_franka = os.path.join(_arena_robot_dir, "franka_panda_hand_on_stand.usd")
        if not os.path.exists(_arena_franka) and os.path.exists(_local_franka):
            os.makedirs(_arena_robot_dir, exist_ok=True)
            os.symlink(_local_franka, _arena_franka)

        self._build_real()

    def _make_args(self) -> argparse.Namespace:
        """Create an argparse Namespace with the fields ArenaEnvBuilder expects."""
        task_seed = getattr(getattr(self.task, "mutation", None), "seed", None)
        seed = task_seed if task_seed is not None else 42
        placement_seed = task_seed if task_seed is not None else None
        return argparse.Namespace(
            num_envs=self._num_envs,
            env_spacing=30.0,
            solve_relations=True,
            placement_seed=placement_seed,
            resolve_on_reset=None,
            mimic=False,
            device=self._device,
            disable_fabric=False,
            headless=self.headless,
            livestream=-1,
            enable_cameras=False,
            experience="",
            kit_args="",
            distributed=False,
            seed=seed,
            presets=None,
        )

    @staticmethod
    def _patch_arena_compatibility() -> None:
        """Inject missing classes/fields that IsaacLab-Arena expects but newer IsaacLab removed."""
        # 1. Fix Nucleus paths to use local assets.
        try:
            import isaaclab.utils.assets as _assets
            _assets.ISAACLAB_NUCLEUS_DIR = "/data/omniverse/Assets/Isaac/6.0/Isaac/IsaacLab"
            _assets.ISAAC_NUCLEUS_DIR = "/data/omniverse/Assets/Isaac/6.0/Isaac"
            _assets.NVIDIA_NUCLEUS_DIR = "/data/omniverse/Assets/Isaac/6.0/NVIDIA"
        except Exception:
            pass

        # 2. Patch Franka embodiment to use local panda_instanceable.usd
        #    (Arena's custom franka_panda_hand_on_stand.usd is not available locally).
        try:
            import isaaclab_arena.embodiments.franka.franka as _franka_mod
            _local_franka = "/data/omniverse/Assets/Isaac/6.0/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd"
            if hasattr(_franka_mod, "_FRANKA_IK_REL_CFG"):
                _franka_mod._FRANKA_IK_REL_CFG.spawn.usd_path = _local_franka
            if hasattr(_franka_mod, "_FRANKA_JOINT_POS_CFG"):
                _franka_mod._FRANKA_JOINT_POS_CFG.spawn.usd_path = _local_franka
        except Exception:
            pass

        # 3. PresetCfg removed from isaaclab_tasks.utils
        try:
            import isaaclab_tasks.utils
            if not hasattr(isaaclab_tasks.utils, "PresetCfg"):
                from dataclasses import dataclass

                @dataclass
                class PresetCfg:
                    pass

                isaaclab_tasks.utils.PresetCfg = PresetCfg
        except Exception:
            pass

        # 4. isaac_teleop / teleop_devices / xr kwargs rejected by
        #    IsaacLabArenaManagerBasedRLEnvCfg (configclass fields frozen at
        #    class creation). Wrap __init__ to swallow unknown kwargs.
        try:
            from isaaclab_arena.environments.isaaclab_arena_manager_based_env import IsaacLabArenaManagerBasedRLEnvCfg

            _orig_init = IsaacLabArenaManagerBasedRLEnvCfg.__init__
            _UNKNOWN_KWARGS = {"isaac_teleop", "teleop_devices", "xr"}

            def _patched_init(self, **kwargs):
                filtered = {k: v for k, v in kwargs.items() if k not in _UNKNOWN_KWARGS}
                return _orig_init(self, **filtered)

            IsaacLabArenaManagerBasedRLEnvCfg.__init__ = _patched_init
        except Exception:
            pass

        # 5. FINGERTIP_LIST removed from newer IsaacLab dexsuite config but
        #    IsaacLab-Arena kuka_allegro embodiment still references it.
        try:
            import isaaclab_tasks.manager_based.manipulation.dexsuite.config.kuka_allegro.dexsuite_kuka_allegro_env_cfg as _kuka_dex_cfg
            if not hasattr(_kuka_dex_cfg, "FINGERTIP_LIST"):
                _kuka_dex_cfg.FINGERTIP_LIST = ["index_link_3", "middle_link_3", "ring_link_3", "thumb_link_3"]
        except Exception:
            pass

    def _build_mock(self) -> None:
        """Mock environment for development without Isaac Sim."""
        self._env = _MockArenaEnv(self.task)

    def reset(self) -> dict[str, Any]:
        if self._env is None:
            raise RuntimeError("Environment not built. Call build() first.")
        self._step_count = 0
        result = self._env.reset()
        # IsaacLab env.reset() returns (obs, info) tuple; extract observation dict
        if isinstance(result, tuple):
            obs = result[0]
        else:
            obs = result
        return self._normalize_obs(obs)

    def step(self, action: Any) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if self._env is None:
            raise RuntimeError("Environment not built. Call build() first.")
        self._step_count += 1
        action = self._normalize_action(action)
        result = self._env.step(action)
        # Gymnasium >= 0.26 returns (obs, reward, terminated, truncated, info)
        if len(result) == 5:
            obs, reward, terminated, truncated, info = result
        else:
            obs, reward, terminated, info = result
            truncated = False
        return self._normalize_obs(obs), float(reward), bool(terminated), bool(truncated), info

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _normalize_obs(self, obs: Any) -> dict[str, Any]:
        """Normalize IsaacLab observation into a standard dict.

        Standard keys:
            eef_pos       (N, 3) or (3,)   end-effector position
            eef_quat      (N, 4) or (4,)   end-effector quaternion (w,x,y,z)
            gripper_pos   (N, 1) or (1,)   gripper joint positions
            object_pos    (N, 3) or (3,)   target object position
            target_pos    (N, 3) or (3,)   goal position (if available)
            _full         raw IsaacLab obs (preserved for advanced use)
        """
        if not isinstance(obs, dict):
            return {"raw": obs}

        result: dict[str, Any] = {}
        policy_obs = obs.get("policy", obs)

        if isinstance(policy_obs, dict):
            result["eef_pos"] = policy_obs.get("eef_pos")
            result["eef_quat"] = policy_obs.get("eef_quat")
            result["gripper_pos"] = policy_obs.get("gripper_pos")
            result["object_pos"] = policy_obs.get("object_pos")
            result["target_pos"] = policy_obs.get("target_pos")
        else:
            result["policy"] = policy_obs

        result["_full"] = obs
        return result

    def _normalize_action(self, action: Any) -> Any:
        """Convert various action formats to Arena-compatible torch.Tensor.

        Supported formats:
            - torch.Tensor   -> passed through
            - numpy.ndarray  -> converted to tensor on env device
            - dict           -> mapped to tensor using known keys
                {"x": float, "y": float, "z": float, "qw/qx/qy/qz": float, "gripper": float}
                or {"0": float, "1": float, ...} for action indices
        """
        import numpy as np
        import torch

        if isinstance(action, torch.Tensor):
            return action
        if isinstance(action, np.ndarray):
            device = getattr(self._env, "device", None) or getattr(
                self._env.unwrapped, "device", torch.device("cuda:0")
            )
            return torch.from_numpy(action).to(device)
        if isinstance(action, dict):
            device = getattr(self._env, "device", None) or getattr(
                self._env.unwrapped, "device", torch.device("cuda:0")
            )
            action_shape = self._env.action_space.shape
            tensor = torch.zeros(action_shape, device=device)
            for key, value in action.items():
                try:
                    v = float(value)
                except (ValueError, TypeError):
                    continue
                if key == "x" or key == "pos_x":
                    tensor[..., 0] = v
                elif key == "y" or key == "pos_y":
                    tensor[..., 1] = v
                elif key == "z" or key == "pos_z":
                    tensor[..., 2] = v
                elif key == "qw":
                    tensor[..., 3] = v
                elif key == "qx":
                    tensor[..., 4] = v
                elif key == "qy":
                    tensor[..., 5] = v
                elif key == "qz":
                    tensor[..., 6] = v
                elif key == "gripper":
                    tensor[..., -1] = v
                elif isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
                    idx = int(key)
                    if 0 <= idx < action_shape[-1]:
                        tensor[..., idx] = v
            return tensor
        return action

    def close(self) -> None:
        if self._env is not None:
            if hasattr(self._env, "close"):
                self._env.close()
            self._env = None
        if self._simulation_app is not None:
            self._simulation_app.close()
            self._simulation_app = None


    def run_policy(
        self,
        policy_config: dict,
        episodes: int | None = None,
        max_steps: int | None = None,
        trace_dir: Path | str | None = None,
    ) -> EvaluationResult:
        """Run a policy for multiple episodes via Arena."""
        import time
        import uuid

        from rosclaw_darwin.evaluation.metrics import compute_basic_metrics
        from rosclaw_darwin.evaluation.result import EvaluationResult

        eps = episodes or self.task.eval.max_episodes or 20
        run_id = f"arena_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        # --- Handle mock / missing environment early ---
        if self._mode == "mock" and not self._explicit_mode:
            return EvaluationResult(
                run_id=run_id,
                task_id=self.task.id,
                policy_id=policy_config.get("policy_id", "unknown"),
                adapter=self.name,
                status="environment_missing",
                metrics={},
                metadata={"error": "Arena repo not found. Set ARENA_REPO or install IsaacLab-Arena."},
            )

        # --- dry-run for real/docker mode: skip build, generate command only ---
        if getattr(self, "_dry_run", False) or policy_config.get("dry_run"):
            arena_repo = self._get_arena_repo()
            if arena_repo is None or not Path(arena_repo).exists():
                return EvaluationResult(
                    run_id=run_id,
                    task_id=self.task.id,
                    policy_id=policy_config.get("policy_id", "unknown"),
                    adapter=self.name,
                    status="environment_missing",
                    metrics={},
                    metadata={"error": "Arena repo not found. Set ARENA_REPO or install IsaacLab-Arena."},
                )
            from rosclaw_darwin.evaluation.arena_runner import ArenaRunner
            runner = ArenaRunner(arena_repo=Path(arena_repo))
            job = {
                "num_episodes": eps,
                "headless": self.headless,
                "timeout_seconds": 600,
            }
            native_config = {}
            if self.task.provenance is not None and hasattr(self.task.provenance, "native_config"):
                native_config = self.task.provenance.native_config or {}
            job.update(native_config)
            cmd = runner._build_command(job)
            return EvaluationResult(
                run_id=run_id,
                task_id=self.task.id,
                policy_id=policy_config.get("policy_id", "unknown"),
                adapter=self.name,
                status="dry_run",
                metrics={},
                command=cmd,
                metadata={"dry_run": True, "arena_repo": str(arena_repo), "mode": self._mode},
            )

        if self._mode == "mock":
            if self._env is None:
                try:
                    self.build()
                except Exception as exc:
                    return EvaluationResult(
                        run_id=run_id,
                        task_id=self.task.id,
                        policy_id=policy_config.get("policy_id", "unknown"),
                        adapter=self.name,
                        status="failed",
                        metrics={},
                        metadata={"error": str(exc)},
                    )
            results = []
            for _ in range(eps):
                obs = self.reset()
                done = False
                step = 0
                max_steps = self.task.eval.max_steps or 1000
                success = False
                collisions = 0
                while not done and step < max_steps:
                    action = {"x": 0.0, "y": 0.0, "z": 0.0, "gripper": 1.0}
                    obs, reward, terminated, truncated, info = self.step(action)
                    step += 1
                    done = terminated or truncated
                    if info.get("collision"):
                        collisions += 1
                    if info.get("success") or reward > 0.9:
                        success = True
                results.append({"success": success, "steps": step, "collisions": collisions, "time": step * 0.05})
            metrics = compute_basic_metrics(results)
            return EvaluationResult(
                run_id=run_id,
                task_id=self.task.id,
                policy_id=policy_config.get("policy_id", "unknown"),
                adapter=self.name,
                status="completed",
                metrics=metrics,
            )

        # --- real / docker / subprocess mode ---
        from rosclaw_darwin.evaluation.arena_runner import ArenaRunner

        if self._mode == "docker":
            runner = ArenaRunner(mode="docker")
            policy_metadata = load_policy_metadata(policy_config)
            # Map ROSClaw task to Arena eval job format
            env_args = self._map_primitives_to_arena_env(self.task)
            env_name = env_args["environment"]
            arena_env_args = {
                "environment": env_name,
                "num_envs": 1,
            }
            # Pass extra env-specific args (object, destinations, etc.)
            for key, value in env_args.items():
                if key != "environment" and value is not None:
                    arena_env_args[key] = value

            # Episode-based evaluation when episodes is specified;
            # otherwise fall back to step-based for quick smoke tests.
            policy_type = policy_config.get("policy_type") or policy_config.get("type", "zero_action")
            # Map ROSClaw short type names to Arena policy names.
            _TYPE_MAP = {"zero": "zero_action", "replay": "replay_action"}
            policy_type = _TYPE_MAP.get(policy_type, policy_type)
            # Map short policy names to full module paths for dynamic import in container.
            # heuristic_policy.py is mounted at /workspace/data/heuristic_policy.py and
            # /workspace/data is on sys.path inside the container.
            if policy_type == "heuristic_lift":
                policy_type = "heuristic_policy.HeuristicLiftPolicy"
            if policy_type == "heuristic_servo_lift":
                policy_type = "heuristic_policy.HeuristicServoLiftPolicy"
            if policy_type == "heuristic_servo_pick":
                policy_type = "heuristic_policy.HeuristicServoPickPolicy"
            if policy_type == "heuristic_servo_goal_pose":
                policy_type = "heuristic_policy.HeuristicServoGoalPosePolicy"
            if policy_type == "cheat_lift":
                policy_type = "heuristic_policy.CheatLiftPolicy"
            if policy_type == "cube_goal_pose_heuristic":
                policy_type = "heuristic_policy.CubeGoalPoseHeuristicPolicy"
            if policy_type == "cheat_cube_goal_pose":
                policy_type = "heuristic_policy.CheatCubeGoalPosePolicy"
            if policy_type == "action_calibration":
                policy_type = "heuristic_policy.ActionCalibrationPolicy"
            if policy_type == "object_validity_audit":
                policy_type = "object_validity_audit_policy.ObjectValidityAuditPolicy"
            if policy_type == "gripper_calibration":
                policy_type = "heuristic_policy.GripperCalibrationPolicy"
            if policy_type == "rotational_calibration":
                policy_type = "heuristic_policy.RotationalCalibrationPolicy"
            if policy_type == "joint_space_calibration":
                policy_type = "heuristic_policy.JointSpaceCalibrationPolicy"
            if policy_type == "replay_action":
                policy_type = "isaaclab_arena.policy.replay_action_policy.ReplayActionPolicy"
            if policy_type == "torchscript":
                policy_type = "isaaclab_arena.policy.torchscript_action_policy.TorchScriptActionPolicy"
            if policy_type == "onnx_wbc":
                policy_type = "isaaclab_arena.policy.onnx_wbc_action_policy.OnnxWbcActionPolicy"
            if policy_type == "rsl_rl":
                policy_type = "isaaclab_arena.policy.rsl_rl_action_policy.RslRlActionPolicy"
            # Forward skill hints into the policy's config dict so Arena-side
            # heuristic policies can consume them. Only pass the key to policies
            # that declare a config_class accepting it; builtin policies like
            # zero_action do not tolerate unknown kwargs.
            policy_config_dict = dict(policy_config.get("policy_config_dict", {}))
            if policy_type.startswith("heuristic_policy."):
                # Preserve hints already inside policy_config_dict; allow top-level override.
                existing_hints = list(policy_config_dict.get("skill_hints", []))
                top_hints = policy_config.get("skill_hints", [])
                policy_config_dict["skill_hints"] = top_hints if top_hints else existing_hints
                # Forward declared object geometry so the policy can adapt thresholds.
                object_geometry = self.task.metadata.get("object_geometry")
                if object_geometry and isinstance(object_geometry, dict):
                    policy_config_dict["object_geometry"] = dict(object_geometry)
                    policy_config_dict.setdefault("use_object_geometry_adaptation", True)
            # For heuristic policies use step-based rollout when no episode count
            # is given so we can observe behaviour across multiple steps even if
            # episodes end early. If episodes are explicitly requested, honour it.
            if policy_type.startswith("heuristic_policy.") and not (eps and eps > 0):
                job = {
                    "name": self.task.id,
                    "arena_env_args": arena_env_args,
                    "num_steps": 200,
                    "policy_type": policy_type,
                    "policy_config_dict": policy_config_dict,
                    "headless": self.headless,
                    "timeout_seconds": 1200,
                }
            elif eps and eps > 0:
                job = {
                    "name": self.task.id,
                    "arena_env_args": arena_env_args,
                    "num_episodes": eps,
                    "policy_type": policy_type,
                    "policy_config_dict": policy_config_dict,
                    "headless": self.headless,
                    "timeout_seconds": 1200,
                }
            else:
                job = {
                    "name": self.task.id,
                    "arena_env_args": arena_env_args,
                    "num_steps": self.task.eval.max_steps or 50,
                    "policy_type": policy_type,
                    "policy_config_dict": policy_config_dict,
                    "headless": self.headless,
                    "timeout_seconds": 3600,
                }
            # Allow task metadata to override Arena env args (e.g. pick a stable environment)
            meta_env_args = self.task.metadata.get("arena_env_args")
            if meta_env_args and isinstance(meta_env_args, dict):
                job["arena_env_args"].update(meta_env_args)

            # Forward seed / placement_seed so the container-side environment can
            # reproduce or vary initial conditions consistently with the host.
            task_seed = getattr(getattr(self.task, "mutation", None), "seed", None)
            if task_seed is not None:
                job["seed"] = int(task_seed)
                job["placement_seed"] = int(task_seed)

            # Forward physics_ablation so the container-side bootstrap can patch
            # procedural object spawn configs (size / friction / mass) for object
            # generalization experiments. Kept outside arena_env_args because the
            # Arena CLI parser does not recognise it.
            physics_ablation = self.task.metadata.get("physics_ablation")
            if physics_ablation and isinstance(physics_ablation, dict):
                job["physics_ablation"] = dict(physics_ablation)

            # Forward asset_policy so the container can detect silent fallback
            # and refuse to run official-benchmark tasks with a fallback asset.
            asset_policy = self.task.metadata.get("asset_policy")
            if asset_policy and isinstance(asset_policy, dict):
                job["asset_policy"] = dict(asset_policy)

            # Merge native config from task provenance if available
            native_config = {}
            if self.task.provenance is not None and hasattr(self.task.provenance, "native_config"):
                native_config = self.task.provenance.native_config or {}
            job.update(native_config)

            # Pass ROSClaw task success conditions so the Arena-side metric
            # computation can align its success/failure classification with the
            # task definition (e.g. object_lifted vs pose_reached).
            job["success_conditions"] = list(self.task.eval.success_conditions or [])

            job["_policy_metadata"] = policy_metadata.model_dump(mode="json")

            # Diagnostic overrides: force a fixed-step rollout regardless of the
            # policy's episode preference. Used by horizon-sweep scripts.
            if max_steps is not None and max_steps > 0:
                job = {k: v for k, v in job.items() if k != "num_episodes"}
                job["num_steps"] = max_steps

            job["_out_dir"] = "/tmp/rosclaw_data/runs"
            if trace_dir is not None:
                job["_trace_dir"] = str(trace_dir)

            if getattr(self, "_dry_run", False) or policy_config.get("dry_run"):
                return EvaluationResult(
                    run_id=run_id,
                    task_id=self.task.id,
                    policy_id=policy_config.get("policy_id", "unknown"),
                    adapter=self.name,
                    status="dry_run",
                    metrics={},
                    command=["docker", "run", self.docker_image if hasattr(self, "docker_image") else "rosclaw-darwin:arena-base"],
                    metadata={"dry_run": True, "mode": "docker"},
                )

            result = runner.run_policy_runner(
                job=job,
                task_id=self.task.id,
                policy_id=policy_config.get("policy_id", "unknown"),
            )
            # Normalize Arena metrics keys so CLI/dashboard can read standard names.
            if result.metrics:
                normalized: dict[str, float] = {}
                for k, v in result.metrics.items():
                    if isinstance(v, (int, float)):
                        if "success_rate" in k:
                            normalized["success_rate"] = float(v)
                        if "num_episodes" in k:
                            normalized["num_episodes"] = float(v)
                        if "num_steps" in k:
                            normalized["num_steps"] = float(v)
                        if "progress" in k:
                            normalized["progress"] = float(v)
                result.metrics.update(normalized)

            # Apply asset-fidelity semantics from the container-side resolution.
            arena_output = result.metadata.get("arena_metrics_output") or {}
            asset_info = arena_output.get("asset_info")
            benchmark_validity = arena_output.get("benchmark_validity")
            if asset_info:
                result.metadata["asset_info"] = asset_info
            if benchmark_validity:
                result.metadata["benchmark_validity"] = benchmark_validity
            can_claim_official = bool(
                benchmark_validity is not None
                and benchmark_validity.get("can_claim_official_benchmark")
            )
            if not can_claim_official:
                # Fallback/diagnostic results must not enter the official leaderboard.
                result.leaderboard_excluded = True
                if result.exclusion_reason is None:
                    result.exclusion_reason = (
                        asset_info.get("fallback_reason")
                        if asset_info
                        else "asset_not_official"
                    )

            # Apply policy-metadata semantics (oracle/cheat exclusion, claim level).
            policy_metadata.apply_exclusion(result)
            if not result.leaderboard_excluded:
                result.metric_scope = MetricScope.arena_real
                result.claim_level = ClaimLevel.capability
            result.metadata["policy_metadata"] = policy_metadata.model_dump(mode="json")

            # Aggregate progress metrics from per-episode traces into top-level metrics.
            episode_metrics = result.metadata.get("episode_metrics")
            if episode_metrics and isinstance(episode_metrics, list):
                result.failure_types = result.metadata.get("failure_counts") or {}
                for key in ("progress_mean", "eef_to_object_distance_min_mean", "object_height_delta_mean", "object_height_max_mean"):
                    if key in result.metadata.get("arena_metrics_output", {}):
                        result.metrics[key] = float(result.metadata["arena_metrics_output"][key])

            # Synthetic metrics fallback for step-based runs without structured output.
            if result.status == "completed" and not result.metrics:
                result.metrics = {
                    "num_steps": float(job.get("num_steps", 0)),
                    "status": 1.0,
                }
            return result

        arena_repo = self._get_arena_repo()
        if arena_repo is None or not Path(arena_repo).exists():
            return EvaluationResult(
                run_id=run_id,
                task_id=self.task.id,
                policy_id=policy_config.get("policy_id", "unknown"),
                adapter=self.name,
                status="environment_missing",
                metrics={},
                metadata={"error": "Arena repo not found. Set ARENA_REPO or install IsaacLab-Arena."},
            )

        runner = ArenaRunner(arena_repo=Path(arena_repo))

        job = {
            "num_episodes": eps,
            "headless": self.headless,
            "timeout_seconds": 600,
        }
        # Merge native config from task provenance if available
        native_config = {}
        if self.task.provenance is not None and hasattr(self.task.provenance, "native_config"):
            native_config = self.task.provenance.native_config or {}
        job.update(native_config)

        # dry-run: only build and save command, do not execute
        if getattr(self, "_dry_run", False) or policy_config.get("dry_run"):
            cmd = runner._build_command(job)
            return EvaluationResult(
                run_id=run_id,
                task_id=self.task.id,
                policy_id=policy_config.get("policy_id", "unknown"),
                adapter=self.name,
                status="dry_run",
                metrics={},
                command=cmd,
                metadata={"dry_run": True, "arena_repo": str(arena_repo)},
            )

        result = runner.run_policy_runner(
            job=job,
            task_id=self.task.id,
            policy_id=policy_config.get("policy_id", "unknown"),
        )
        return result


    def _map_primitives_to_arena_env(self, task: Task) -> dict[str, Any]:
        """Map ROSClaw primitives to a valid IsaacLab-Arena example environment.

        First tries the declarative capability registry; if the match is too weak
        or fails, falls back to the legacy hard-coded mapping.
        """
        registry_args = _map_task_to_arena_env(task, self.robot)
        if registry_args is not None:
            return registry_args

        # --- Legacy hard-coded fallback ---
        primitive_names = {p.name.lower() for p in task.primitives}
        raw_obj = task.objects[0].name if task.objects else "object"
        mapped_obj = _ArenaComponentMapper._OBJECT_MAP.get(raw_obj, raw_obj)
        if mapped_obj == "object" or mapped_obj not in _ArenaComponentMapper._LOCAL_ARENA_OBJECTS:
            mapped_obj = "dex_cube"

        scene_name = _ArenaComponentMapper._SCENE_MAP.get(
            (task.scene.name or task.scene.domain or "default").lower(), "procedural_table"
        )

        if scene_name == "kitchen" and primitive_names & {"pick", "place", "open", "close"}:
            if "place" in primitive_names and "close" in primitive_names:
                return {
                    "environment": "franka_put_and_close_door",
                    "object": mapped_obj,
                    "embodiment": _ArenaComponentMapper._ROBOT_MAP.get(self.robot, self.robot),
                }
            return {
                "environment": "kitchen_pick_and_place",
                "object": mapped_obj,
                "embodiment": "franka_joint_pos",
            }

        env_args: dict[str, Any] = {
            "environment": "lift_object",
            "object": mapped_obj,
            "embodiment": _ArenaComponentMapper._ROBOT_MAP.get(self.robot, self.robot),
        }

        if "sort" in primitive_names:
            return {
                "environment": "tabletop_sort_cubes",
                "objects": ["red_cube", "green_cube"],
                "destinations": ["red_container", "green_container"],
                "background": "table",
                "embodiment": "franka_ik",
            }

        if "press" in primitive_names:
            return {
                "environment": "press_button",
                "object": "coffee_machine",
                "embodiment": "franka_ik",
            }

        if primitive_names & {"open", "close"}:
            return {
                "environment": "lift_object",
                "object": mapped_obj if mapped_obj != "object" else "dex_cube",
                "embodiment": "franka_joint_pos",
            }

        if primitive_names & {"pick", "place"}:
            return {
                "environment": "lift_object",
                "object": mapped_obj if mapped_obj != "object" else "dex_cube",
                "embodiment": "franka_joint_pos",
            }

        if "lift" in primitive_names:
            return {
                "environment": "lift_object",
                "object": mapped_obj if mapped_obj != "object" else "dex_cube",
                "embodiment": "franka_joint_pos",
            }

        return env_args

    def get_state(self) -> dict[str, Any]:
        return {
            **super().get_state(),
            "backend": self._mode,
            "robot": self.robot,
            "step_count": self._step_count,
        }

    def _get_arena_repo(self) -> str | None:
        import os
        return os.environ.get("ROSCLAW_ARENA_REPO") or os.environ.get("ARENA_REPO")

    @classmethod
    def create_in_container(
        cls,
        task: Task,
        container_name: str = "rosclaw_darwin",
        **kwargs: Any,
    ) -> "ArenaAdapter":
        """Create an adapter that runs inside a Docker container."""
        import os

        os.environ["ROSCLAW_ARENA_MODE"] = "docker"
        return cls(task, **kwargs)


class _MockArenaEnv:
    """Minimal mock that satisfies the gym-like interface for unit tests."""

    def __init__(self, task: Task):
        self.task = task
        self._step = 0
        self._max_steps = (task.eval.max_steps or 1000)
        # Gym-like action_space for policy shape inference.
        import gymnasium as gym
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(8,), dtype=float)
        self.device = "cpu"

    def reset(self) -> dict[str, Any]:
        self._step = 0
        self._grasped = False
        # Return standardized observation so policies can be tested in mock mode.
        import numpy as np

        self._eef_pos = np.array([0.35, 0.0, 0.25], dtype=float)
        self._object_pos = np.array([0.35, 0.0, 0.07], dtype=float)
        self._gripper_pos = np.array([0.04], dtype=float)
        self._eef_quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
        return {
            "policy": {
                "eef_pos": self._eef_pos,
                "eef_quat": self._eef_quat,
                "gripper_pos": self._gripper_pos,
                "object_pos": self._object_pos,
            },
            "task_id": self.task.id,
        }

    def step(self, action: Any) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        self._step += 1
        import numpy as np
        import torch

        # Parse action to get target position and gripper command
        target_pos = None
        gripper_cmd = 1.0

        if isinstance(action, dict):
            target_pos = np.array([
                action.get("x", self._eef_pos[0]),
                action.get("y", self._eef_pos[1]),
                action.get("z", self._eef_pos[2]),
            ], dtype=float)
            gripper_cmd = action.get("gripper", 1.0)
        elif isinstance(action, torch.Tensor) or hasattr(action, "numpy"):
            a = action.detach().cpu().numpy() if hasattr(action, "detach") else np.array(action)
            if a.ndim > 1:
                a = a[0]
            if len(a) >= 3:
                target_pos = np.array([float(a[0]), float(a[1]), float(a[2])], dtype=float)
            if len(a) > 7:
                gripper_cmd = float(a[7])

        # Move eef toward target (proportional control, slower for realistic IK)
        if target_pos is not None:
            error = target_pos - self._eef_pos
            self._eef_pos += error * 0.08  # 8% per step toward target

        # Update gripper
        if gripper_cmd < 0:
            self._gripper_pos[0] = max(self._gripper_pos[0] - 0.008, 0.0)
        else:
            self._gripper_pos[0] = min(self._gripper_pos[0] + 0.008, 0.04)

        # Sticky grasp: once grasped, object follows eef until gripper opens
        dist = np.linalg.norm(self._eef_pos - self._object_pos)
        if not self._grasped:
            self._grasped = dist < 0.06 and self._gripper_pos[0] < 0.02
        else:
            # Release if gripper opens significantly
            if self._gripper_pos[0] > 0.02:
                self._grasped = False
        if self._grasped:
            self._object_pos = self._eef_pos.copy() + np.array([0.0, 0.0, -0.05])

        # Success: object lifted above table
        success = self._grasped and self._object_pos[2] > 0.15
        terminated = self._step >= self._max_steps or success
        reward = 10.0 if success else (1.0 if self._grasped else max(0.0, 0.5 - dist))
        info = {"step": self._step, "mock": True, "success": success, "grasped": self._grasped}
        obs = {
            "policy": {
                "eef_pos": self._eef_pos.copy(),
                "eef_quat": self._eef_quat.copy(),
                "gripper_pos": self._gripper_pos.copy(),
                "object_pos": self._object_pos.copy(),
            },
            "task_id": self.task.id,
        }
        return obs, reward, terminated, False, info

    def close(self) -> None:
        pass
