"""Stub for isaaclab_teleop."""
from dataclasses import dataclass, field
from typing import Any

@dataclass
class IsaacTeleopCfg:
    pass

@dataclass
class XrCfg:
    anchor_pos: Any = None
    anchor_rot: Any = None
    anchor_prim_path: str = ""
    anchor_rotation_mode: Any = None
    fixed_anchor_height: bool = False

def create_isaac_teleop_device(*args, **kwargs):
    return None

def remove_camera_configs(*args, **kwargs):
    pass
