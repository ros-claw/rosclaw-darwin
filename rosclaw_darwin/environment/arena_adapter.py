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
from typing import Any

from rosclaw_darwin.tdl.schema import Task
from .base import BaseEnvironmentAdapter


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
    _OBJECT_MAP: dict[str, str] = {
        # Nucleus-backed assets (requires Omniverse connection).
        "milk_carton": "milk_carton_hope_robolab",
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
        "spoon": "spoon_handal_robolab",
        "fork": "salad_tongs_handal_robolab",
        "knife": "serving_spoon_handal_robolab",
        "plate": "clay_plates_hot3d_robolab",
        "cup": "ceramic_mug_hot3d_robolab",
        "bottle": "beer_bottle_hot3d_robolab",
        "can": "soup_can_hot3d_robolab",
        "box": "brown_box",
        "cube": "dex_cube",
        "sphere": "sphere",
        "bin": "blue_sorting_bin",
        "container": "red_container",
        # Procedural fallback assets (no Nucleus required).
        "procedural_cube": "procedural_cube",
    }

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
        "franka_joint": "franka_joint",
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
        bg_name = self._SCENE_MAP.get(self.task.scene, "procedural_table")
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
        if hasattr(_procedural_cls, "_generate_rigid_cfg"):
            _orig_generate = _procedural_cls._generate_rigid_cfg

            def _patched_generate(self):
                cfg = _orig_generate(self)
                if hasattr(cfg, "spawn") and cfg.spawn is not None:
                    cfg.spawn.activate_contact_sensors = True
                return cfg

            _procedural_cls._generate_rigid_cfg = _patched_generate

        # Place objects closer to the robot's initial reach (x~0.45) so the
        # end-effector doesn't need to travel far horizontally.
        for idx, obj in enumerate(self.task.objects):
            # Each object needs a unique prim path to avoid USD stage collisions.
            prim_path = f"{{ENV_REGEX_NS}}/{obj.name}"
            inst = _procedural_cls(instance_name=obj.name, prim_path=prim_path)
            from isaaclab_arena.utils.pose import Pose
            # z=0.07 places object bottom at table top (z=0.02) for procedural cube
            # with half-height 0.05. Previous z=0.05 caused object to spawn inside table.
            inst.set_initial_pose(Pose(position_xyz=(0.35 + idx * 0.05, 0.0, 0.07)))
            arena_objects.append(inst)

        # If no objects were mapped at all, add a procedural cube so that
        # manipulation tasks have something to interact with.
        if not arena_objects:
            inst = _procedural_cls(instance_name="object", prim_path="{ENV_REGEX_NS}/object")
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
        """Create an Arena Embodiment from the robot field."""
        from isaaclab_arena.embodiments.franka.franka import FrankaIKEmbodiment
        from isaaclab_arena.embodiments.kuka_allegro.kuka_allegro import KukaAllegroEmbodiment

        robot = self._ROBOT_MAP.get(self.robot, "franka_ik")
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
                if hasattr(embodiment.action_config.arm_action, "controller"):
                    embodiment.action_config.arm_action.controller.use_relative_mode = False
                # Scale=0.5 halves position targets and corrupts quaternions in
                # absolute mode. Set to 1.0 so action = actual target pose.
                if hasattr(embodiment.action_config.arm_action, "scale"):
                    embodiment.action_config.arm_action.scale = 1.0
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
            episode_length_s=self.task.eval_config.timeout_seconds,
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
            episode_length_s=self.task.eval_config.timeout_seconds,
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
            episode_length_s=self.task.eval_config.timeout_seconds,
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
            episode_length_s=self.task.eval_config.timeout_seconds,
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
            episode_length_s=self.task.eval_config.timeout_seconds,
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
            episode_length_s=self.task.eval_config.timeout_seconds,
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
            episode_length_s=self.task.eval_config.timeout_seconds,
            task_description=self.task.description or None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_primitive_target(self, primitive_name: str, registry, arena_objects):
        """Find the Arena object associated with a primitive's target."""
        for p in self.task.primitives:
            if p.name == primitive_name and p.target:
                # First try arena_objects list (already mapped).
                for obj in arena_objects:
                    if getattr(obj, "name", None) == p.target:
                        return obj
                    # Also check against the mapped name.
                    mapped = self._OBJECT_MAP.get(p.target, p.target)
                    if getattr(obj, "name", None) == mapped:
                        return obj
                # Not found in arena_objects: try registry directly.
                try:
                    mapped = self._OBJECT_MAP.get(p.target, p.target)
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
        self._mode = mode or self._detect_mode()
        self._step_count = 0
        self._simulation_app: Any | None = None
        self._num_envs = num_envs
        self._device = device

    @staticmethod
    def _detect_mode() -> str:
        import os

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
            _local_franka = "/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd"
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
                        "--/persistent/isaac/asset_root/default": "/data/omniverse/Assets/Isaac/5.1",
                        "--/persistent/isaac/asset_root/cloud": "/data/omniverse/Assets/Isaac/5.1",
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
        _arena_robot_dir = "/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab/Arena/assets/robot_library"
        _local_franka = "/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd"
        _arena_franka = os.path.join(_arena_robot_dir, "franka_panda_hand_on_stand.usd")
        if not os.path.exists(_arena_franka) and os.path.exists(_local_franka):
            os.makedirs(_arena_robot_dir, exist_ok=True)
            os.symlink(_local_franka, _arena_franka)

        self._build_real()

    def _make_args(self) -> argparse.Namespace:
        """Create an argparse Namespace with the fields ArenaEnvBuilder expects."""
        return argparse.Namespace(
            num_envs=self._num_envs,
            env_spacing=30.0,
            solve_relations=True,
            placement_seed=None,
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
            seed=42,
            presets=None,
        )

    @staticmethod
    def _patch_arena_compatibility() -> None:
        """Inject missing classes/fields that IsaacLab-Arena expects but newer IsaacLab removed."""
        # 1. Fix Nucleus paths to use local assets.
        try:
            import isaaclab.utils.assets as _assets
            _assets.ISAACLAB_NUCLEUS_DIR = "/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab"
            _assets.ISAAC_NUCLEUS_DIR = "/data/omniverse/Assets/Isaac/5.1/Isaac"
            _assets.NVIDIA_NUCLEUS_DIR = "/data/omniverse/Assets/Isaac/5.1/NVIDIA"
        except Exception:
            pass

        # 2. Patch Franka embodiment to use local panda_instanceable.usd
        #    (Arena's custom franka_panda_hand_on_stand.usd is not available locally).
        try:
            import isaaclab_arena.embodiments.franka.franka as _franka_mod
            _local_franka = "/data/omniverse/Assets/Isaac/5.1/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd"
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
        import torch
        import numpy as np

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
                v = float(value)
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

    def get_state(self) -> dict[str, Any]:
        return {
            **super().get_state(),
            "backend": self._mode,
            "robot": self.robot,
            "step_count": self._step_count,
        }

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
        self._max_steps = task.eval_config.max_steps
        # Gym-like action_space for policy shape inference.
        import gymnasium as gym
        self.action_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(8,), dtype=float)
        self.device = "cpu"

    def reset(self) -> dict[str, Any]:
        self._step = 0
        return {"observation": "mock_reset", "task_id": self.task.id}

    def step(self, action: Any) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        self._step += 1
        terminated = self._step >= self._max_steps
        reward = 1.0 if terminated else 0.0
        info = {"step": self._step, "mock": True}
        obs = {"observation": f"mock_step_{self._step}", "action": action}
        return obs, reward, terminated, False, info

    def close(self) -> None:
        pass
