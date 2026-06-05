from dataclasses import dataclass, field
from typing import Any

@dataclass
class MJWarpSolverCfg:
    solver: str = "newton"
    integrator: str = "implicitfast"
    njmax: int = 300
    nconmax: int = 400
    impratio: float = 10.0
    cone: str = "elliptic"
    update_data_interval: int = 2
    iterations: int = 100
    ls_iterations: int = 15
    ls_parallel: bool = False
    use_mujoco_contacts: bool = False
    ccd_iterations: int = 15000

@dataclass
class NewtonCfg:
    solver_cfg: Any = field(default_factory=MJWarpSolverCfg)
    num_substeps: int = 2
    debug_mode: bool = False
