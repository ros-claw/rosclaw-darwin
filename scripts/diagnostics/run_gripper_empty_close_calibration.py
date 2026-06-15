#!/usr/bin/env python3
"""Wrapper that runs gripper empty-close calibration."""

from __future__ import annotations

import run_gripper_calibration

if __name__ == "__main__":
    import sys

    # Force scenario before any user args.
    argv = [sys.argv[0], "--scenario", "empty_close"] + sys.argv[1:]
    run_gripper_calibration.main(argv)
