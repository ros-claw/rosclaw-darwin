#!/usr/bin/env python3
"""Generate FailureToHint v3.4 evidence-status JSON from paired evaluation.

Reads the v3.4 rule YAML and the paired-evaluation summary, evaluates every
recipe through ``PromotionManager``, and writes ``fth_v34_evidence_status.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rosclaw_darwin.evolution.hint_recipe import HintRecipe  # noqa: E402
from rosclaw_darwin.evolution.promotion_manager import PromotionManager  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate FTH v3.4 evidence status from paired evaluation"
    )
    parser.add_argument(
        "--rules",
        default="configs/skills/failure_signature_to_hint_rules_v34.yaml",
        help="Path to v3.4 rules YAML",
    )
    parser.add_argument(
        "--paired-summary",
        default="data_v20/paired/official_seed24_micro_recovery_0_199/paired_summary.json",
        help="Path to paired summary JSON",
    )
    parser.add_argument(
        "--out",
        default="data_v20/evolution/fth_v34_evidence_status.json",
        help="Output evidence-status JSON path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    paired_summary_path = Path(args.paired_summary)
    paired_summary = None
    if paired_summary_path.exists():
        paired_summary = json.loads(paired_summary_path.read_text(encoding="utf-8"))
        # The summary JSON contains both summary and outcomes; the promotion
        # manager only needs the summary block.
        if "summary" in paired_summary:
            paired_summary = paired_summary["summary"]

    manager = PromotionManager.from_summary_dict(paired_summary)

    rules_yaml = yaml.safe_load(Path(args.rules).read_text(encoding="utf-8"))
    rules = rules_yaml.get("rules", [])

    statuses: list[dict] = []
    for rule in rules:
        recipe = HintRecipe.model_validate(rule)
        status = manager.evaluate(recipe)
        statuses.append(status.model_dump(mode="json"))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "statuses": statuses,
                "summary_source": str(paired_summary_path.resolve()),
            },
            indent=2,
        )
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
