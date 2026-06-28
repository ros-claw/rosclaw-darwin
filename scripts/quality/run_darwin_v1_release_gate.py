#!/usr/bin/env python3
"""ROSClaw-Darwin v1.0 release gate runner.

Executes required checks and reports pass/fail.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def run_command(cmd: list[str], label: str) -> tuple[bool, str]:
    print(f"\n[CHECK] {label}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    except subprocess.TimeoutExpired:
        return False, f"{label}: timed out"
    ok = result.returncode == 0
    return ok, (result.stdout + result.stderr).strip()


def check_files_exist(required: list[str]) -> tuple[bool, list[str]]:
    missing = [p for p in required if not Path(p).exists()]
    return not missing, [f"Missing required file: {p}" for p in missing]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Darwin v1.0 release gate")
    parser.add_argument("--config", type=Path, default=Path("configs/release/darwin_v1_release_gate.yaml"))
    args = parser.parse_args(argv)

    config = load_config(args.config)
    required = config.get("required_checks", {})

    results: list[tuple[str, bool, str]] = []

    if required.get("unit_tests"):
        ok, out = run_command(["python", "-m", "pytest", "tests/unit", "-q"], "unit tests")
        results.append(("unit_tests", ok, out))

    if required.get("integration_tests"):
        ok, out = run_command(["python", "-m", "pytest", "tests/integration", "-q"], "integration tests")
        results.append(("integration_tests", ok, out))

    if required.get("cli_smoke"):
        ok, out = run_command(["darwin", "--help"], "CLI help")
        results.append(("cli_smoke", ok, out))

    if required.get("dashboard_loaders"):
        ok, out = run_command(["python", "-m", "pytest", "tests/integration/test_dashboard_v1_views.py", "-q"], "dashboard loaders")
        results.append(("dashboard_loaders", ok, out))

    if required.get("evidence_cards"):
        ok, out = run_command(["python", "scripts/quality/check_claim_boundaries.py"], "claim boundaries")
        results.append(("evidence_cards", ok, out))

    if required.get("docs_exist"):
        ok, errs = check_files_exist(config.get("required_docs", []))
        results.append(("docs_exist", ok, "\n".join(errs)))

    print("\n" + "=" * 50)
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if not ok:
            print(detail[:500])

    if failed:
        print(f"\nRelease gate FAILED: {len(failed)} check(s) failed.")
        return 1
    print("\nRelease gate PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
