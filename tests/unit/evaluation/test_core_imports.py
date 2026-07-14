"""Tests that the evaluation core does not import torch or lerobot at load time."""

from __future__ import annotations

import sys


def test_backend_module_does_not_import_torch_or_lerobot() -> None:
    """Importing the backend must not pull torch/lerobot into sys.modules."""
    # Remove any prior imports to get a clean observation.
    before = set(sys.modules.keys())
    from rosclaw_darwin.evaluation.backends.lerobot import LeRobotEvalBackend  # noqa: F401

    after = set(sys.modules.keys())
    new_modules = after - before
    forbidden = {"torch", "lerobot", "torch.cuda"}
    found = {m.split(".")[0] for m in new_modules} & forbidden
    assert not found, f"Forbidden modules loaded: {found}"


def test_cli_eval_app_does_not_import_torch_or_lerobot() -> None:
    """Importing the eval CLI must not pull torch/lerobot into sys.modules."""
    before = set(sys.modules.keys())
    from rosclaw_darwin.cli.eval_app import eval_app  # noqa: F401

    after = set(sys.modules.keys())
    new_modules = after - before
    forbidden = {"torch", "lerobot"}
    found = {m.split(".")[0] for m in new_modules} & forbidden
    assert not found, f"Forbidden modules loaded: {found}"
