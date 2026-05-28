"""Stub for isaaclab_newton.physics.newton_manager_cfg.

IsaacLab-Arena imports NewtonCfg and MJWarpSolverCfg even when the
isaaclab_newton package is not installed. This stub provides minimal
dataclasses so the import succeeds and physx-only workflows work.
"""
from dataclasses import dataclass, field


@dataclass
class MJWarpSolverCfg:
    solver: str = ""
    integrator: str = ""
    njmax: int = 0
    nconmax: int = 0
    impratio: float = 0.0
    cone: str = ""
    update_data_interval: int = 0
    iterations: int = 0
    ls_iterations: int = 0
    ls_parallel: bool = False
    use_mujoco_contacts: bool = False
    ccd_iterations: int = 0


@dataclass
class NewtonCfg:
    solver_cfg: MJWarpSolverCfg = field(default_factory=MJWarpSolverCfg)
    num_substeps: int = 0
    debug_mode: bool = False
