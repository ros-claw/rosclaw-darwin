#!/usr/bin/env python3
"""Audit paired evaluation for missed stderr infrastructure failures.

After the runner patches, every stderr containing a BlockingIOError / traceback /
HDF5 lock error must produce an ``invalid_pair`` with an
``infrastructure_failure`` note.  This script verifies that invariant and prints
any offending seeds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_INFRA_PATTERNS = {
    "blocking_io_error": re.compile(r"BlockingIOError", re.IGNORECASE),
    "python_traceback": re.compile(r"Traceback \(most recent call last\)"),
    "hdf5_lock_error": re.compile(r"unable to lock file", re.IGNORECASE),
    "h5py_error": re.compile(r"\bh5py\.", re.IGNORECASE),
    "cuda_oom": re.compile(r"CUDA out of memory", re.IGNORECASE),
    "no_space_left": re.compile(r"No space left on device", re.IGNORECASE),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit paired evaluation for missed infrastructure failures"
    )
    parser.add_argument(
        "--paired-dir",
        default="data_v20/paired/official_seed24_micro_recovery_0_199",
        help="Paired evaluation output directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.paired_dir)
    if not root.exists():
        print(f"Directory not found: {root}", file=sys.stderr)
        return 1

    missed: list[dict] = []
    for seed_dir in sorted(root.glob("seed_*")):
        pair_path = seed_dir / "pair_result.json"
        if not pair_path.exists():
            continue
        pair = json.loads(pair_path.read_text(encoding="utf-8"))
        notes = pair.get("notes", [])
        flagged_in_notes = any("infrastructure" in n or "runner_status" in n for n in notes)

        for side in ("baseline", "candidate"):
            stderr_path = seed_dir / side / "stderr.log"
            if not stderr_path.exists():
                continue
            text = stderr_path.read_text(errors="replace")
            signals = [n for n, p in _INFRA_PATTERNS.items() if p.search(text)]
            if signals and not flagged_in_notes:
                missed.append(
                    {
                        "seed": seed_dir.name,
                        "side": side,
                        "stderr_signals": signals,
                        "notes": notes,
                    }
                )

    if missed:
        print(f"MISSED INFRASTRUCTURE FAILURES: {len(missed)}")
        for item in missed:
            print(item)
        return 1

    print("OK: all stderr infrastructure failures are flagged in pair_result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
