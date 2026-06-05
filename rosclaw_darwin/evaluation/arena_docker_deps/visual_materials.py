# Copyright (c) 2022-2026, The Isaac Lab Project Developers.
# All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
#
# PATCHED for Isaac Sim 5.1 compatibility.
# The upstream code passes `name="Shader"` to CreateShaderPrimFromSdrCommand,
# but the Isaac Sim 5.1 extension does not accept that kwarg. This patch falls
# back to calling without `name` and dynamically discovers the created prim.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from omni.usd.commands import CreateMdlMaterialPrimCommand, CreateShaderPrimFromSdrCommand
from pxr import Usd, UsdShade

from isaaclab.sim.utils import clone, safe_set_attribute_on_usd_prim
from isaaclab.sim.utils.stage import get_current_stage
from isaaclab.utils.assets import NVIDIA_NUCLEUS_DIR

if TYPE_CHECKING:
    from . import visual_materials_cfg

logger = logging.getLogger(__name__)


@clone
def spawn_preview_surface(prim_path: str, cfg: visual_materials_cfg.PreviewSurfaceCfg) -> Usd.Prim:
    """Create a preview surface prim and override the settings with the given config."""
    stage = get_current_stage()

    if not stage.GetPrimAtPath(prim_path).IsValid():
        material_prim = UsdShade.Material.Define(stage, prim_path)
        if material_prim:
            try:
                shader_prim = CreateShaderPrimFromSdrCommand(
                    parent_path=prim_path,
                    identifier="UsdPreviewSurface",
                    stage_or_context=stage,
                    name="Shader",
                ).do()
            except TypeError:
                # Isaac Sim 5.1 fallback: older extension does not accept `name`
                logger.debug("CreateShaderPrimFromSdrCommand does not accept `name`, falling back")
                shader_prim = CreateShaderPrimFromSdrCommand(
                    parent_path=prim_path,
                    identifier="UsdPreviewSurface",
                    stage_or_context=stage,
                ).do()

            if shader_prim:
                surface_out = shader_prim.GetOutput("surface")
                if surface_out:
                    material_prim.CreateSurfaceOutput().ConnectToSource(surface_out)

                displacement_out = shader_prim.GetOutput("displacement")
                if displacement_out:
                    material_prim.CreateDisplacementOutput().ConnectToSource(displacement_out)
        else:
            raise ValueError(f"Failed to create preview surface shader at path: '{prim_path}'.")
    else:
        raise ValueError(f"A prim already exists at path: '{prim_path}'.")

    # Dynamic prim discovery: try /Shader first, then first valid child
    prim = stage.GetPrimAtPath(f"{prim_path}/Shader")
    if not prim.IsValid():
        parent = stage.GetPrimAtPath(prim_path)
        if parent.IsValid():
            for child in parent.GetChildren():
                if child.IsValid():
                    prim = child
                    break
    if not prim.IsValid():
        raise ValueError(f"Failed to create preview surface material at path: '{prim_path}'.")

    cfg = cfg.to_dict()  # type: ignore
    del cfg["func"]
    for attr_name, attr_value in cfg.items():
        safe_set_attribute_on_usd_prim(prim, f"inputs:{attr_name}", attr_value, camel_case=True)

    return prim


@clone
def spawn_from_mdl_file(
    prim_path: str, cfg: visual_materials_cfg.MdlFileCfg | visual_materials_cfg.GlassMdlCfg
) -> Usd.Prim:
    """Load a material from its MDL file and override the settings with the given config."""
    stage = get_current_stage()

    if not stage.GetPrimAtPath(prim_path).IsValid():
        material_name = cfg.mdl_path.split("/")[-1].split(".")[0]
        CreateMdlMaterialPrimCommand(
            mtl_url=cfg.mdl_path.format(NVIDIA_NUCLEUS_DIR=NVIDIA_NUCLEUS_DIR),
            mtl_name=material_name,
            mtl_path=prim_path,
            stage=stage,
            select_new_prim=False,
        ).do()
    else:
        raise ValueError(f"A prim already exists at path: '{prim_path}'.")

    prim = stage.GetPrimAtPath(f"{prim_path}/Shader")
    if not prim.IsValid():
        raise ValueError(f"Failed to create MDL material at path: '{prim_path}'.")

    cfg = cfg.to_dict()  # type: ignore
    del cfg["func"]
    del cfg["mdl_path"]
    for attr_name, attr_value in cfg.items():
        safe_set_attribute_on_usd_prim(prim, f"inputs:{attr_name}", attr_value, camel_case=False)

    return prim
