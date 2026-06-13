#!/usr/bin/env python3
"""Action-response calibration for lift_object.

Runs small fixed actions along each world axis and measures the resulting
end-effector displacement. Produces a calibration JSON that maps commanded
action axes to world displacement directions and magnitudes.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.report import save_run_result
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.utils.paths import ensure_dir


def _load_policy_config(path: str) -> dict[str, Any]:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("policy_id", Path(path).stem)
    return cfg


def _extract_eef_positions(run_dir: Path) -> list[dict[str, float]]:
    """Read eef positions from the saved run metadata."""
    run_path = run_dir / "run.json"
    if run_path.exists():
        try:
            data = json.loads(run_path.read_text())
            am = data.get("metadata", {}).get("arena_metrics_output", {})
            eps = am.get("episode_metrics", [])
            if eps:
                first = eps[0]
                last = eps[-1]
                return [
                    {
                        "x": first.get("eef_x_initial", 0.0),
                        "y": first.get("eef_y_initial", 0.0),
                        "z": first.get("eef_z_initial", 0.0),
                    },
                    {
                        "x": last.get("eef_x_final", 0.0),
                        "y": last.get("eef_y_final", 0.0),
                        "z": last.get("eef_z_final", 0.0),
                    },
                ]
        except Exception:
            pass
    return []


def _compute_axis_response(run_dir: Path, axis: int, sign: float, magnitude: float) -> dict[str, Any]:
    """Compute world displacement for a single action-axis run."""
    positions = _extract_eef_positions(run_dir)
    if len(positions) < 2:
        return {
            "world_delta_mean": [None, None, None],
            "response_norm": None,
            "valid": False,
        }
    delta = [
        positions[-1]["x"] - positions[0]["x"],
        positions[-1]["y"] - positions[0]["y"],
        positions[-1]["z"] - positions[0]["z"],
    ]
    # Divide by commanded magnitude to get displacement per action unit.
    normalized = [d / magnitude if magnitude else 0.0 for d in delta]
    return {
        "world_delta_mean": delta,
        "world_delta_per_unit": normalized,
        "response_norm": (sum(d ** 2 for d in delta) ** 0.5),
        "valid": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Action response calibration")
    parser.add_argument("--task", default="examples/tasks/native/lift_object.yaml")
    parser.add_argument("--out", default="/tmp/rosclaw_data/calibrations/action_response")
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--magnitude", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out_dir = ensure_dir(args.out)
    task = TaskLoader().load(args.task)
    adapter = ArenaAdapter(task)

    axes = [
        ("action_x_pos", 0, 1.0),
        ("action_x_neg", 0, -1.0),
        ("action_y_pos", 1, 1.0),
        ("action_y_neg", 1, -1.0),
        ("action_z_pos", 2, 1.0),
        ("action_z_neg", 2, -1.0),
    ]

    axis_results: dict[str, Any] = {}
    run_meta: list[dict[str, Any]] = []

    for label, axis, sign in axes:
        policy_config = {
            "policy_id": f"calibration_{label}",
            "type": "action_calibration",
            "policy_config_dict": {
                "calibration_axis": axis,
                "calibration_sign": sign,
                "calibration_magnitude": args.magnitude,
            },
        }
        if args.dry_run:
            policy_config["dry_run"] = True

        print(f"[calibration] running {label} axis={axis} sign={sign}")
        result = adapter.run_policy(policy_config, episodes=None, max_steps=args.steps)
        run_dir = out_dir / result.run_id
        save_run_result(
            run_dir=run_dir,
            result=result,
            task_yaml=task.to_yaml(),
            policy_config=policy_config,
        )
        axis_results[label] = _compute_axis_response(run_dir, axis, sign, args.magnitude)
        run_meta.append({
            "label": label,
            "run_id": result.run_id,
            "status": result.status,
            "axis": axis,
            "sign": sign,
        })
        print(f"  run={result.run_id} delta={axis_results[label]['world_delta_mean']} norm={axis_results[label]['response_norm']}")

    # Estimate mapping from action axis to world displacement direction.
    estimated_mapping: dict[str, str] = {}
    for world_axis, idx in [("x", 0), ("y", 1), ("z", 2)]:
        best_label = None
        best_corr = -1.0
        for label, _, sign in axes:
            res = axis_results[label]
            if not res["valid"]:
                continue
            per_unit = res["world_delta_per_unit"]
            proj = per_unit[idx] if per_unit[idx] is not None else 0.0
            if abs(proj) > best_corr:
                best_corr = abs(proj)
                direction = "positive" if proj > 0 else "negative"
                best_label = f"{direction}_{label.split('_', 2)[1]}"
        estimated_mapping[f"world_{world_axis}_to_action_axis"] = best_label or "unknown"

    # Recommend a gain multiplier based on typical displacement.
    valid_norms = [r["response_norm"] for r in axis_results.values() if r["valid"] and r["response_norm"]]
    recommended_gain = 1.0
    if valid_norms:
        avg_response = sum(valid_norms) / len(valid_norms)
        # Target ~1 cm per step effective displacement.
        recommended_gain = round(0.01 / max(avg_response, 1e-6), 2)

    calibration = {
        "task_id": task.id,
        "policy_action_mode": "relative_pose_dik",
        "calibration_steps": args.steps,
        "action_magnitude": args.magnitude,
        "axes": axis_results,
        "estimated_mapping": estimated_mapping,
        "recommended_gain_multiplier": recommended_gain,
        "runs": run_meta,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    (out_dir / "action_response_calibration.json").write_text(json.dumps(calibration, indent=2))

    report_path = Path("reports/ACTION_RESPONSE_CALIBRATION_REPORT.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(calibration))
    print(f"[calibration] saved to {out_dir / 'action_response_calibration.json'}")
    print(f"[calibration] report saved to {report_path}")


def _render_report(calibration: dict[str, Any]) -> str:
    lines = [
        "# Action Response Calibration Report",
        "",
        f"- Task: ``{calibration['task_id']}``",
        f"- Action mode: ``{calibration['policy_action_mode']}``",
        f"- Calibration steps per axis: {calibration['calibration_steps']}",
        f"- Recommended gain multiplier: {calibration['recommended_gain_multiplier']}",
        "",
        "## Axis Responses",
        "",
        "| action | world delta (m) | response norm (m) | per-unit delta |",
        "|---|---|---|---|",
    ]
    for label, res in calibration["axes"].items():
        delta = res["world_delta_mean"]
        per_unit = res.get("world_delta_per_unit", [None, None, None])
        lines.append(
            f"| {label} | {delta} | {res['response_norm']} | {per_unit} |"
        )
    lines.extend([
        "",
        "## Estimated Mapping",
        "",
        "```json",
        json.dumps(calibration["estimated_mapping"], indent=2),
        "```",
        "",
        "## Interpretation",
        "",
        "- A positive action on axis X producing a negative world X displacement",
        "  indicates a body-frame sign flip.",
        "- Small response norms confirm the DifferentialIK controller is heavily",
        "  damped; increasing the commanded magnitude or using joint-space control",
        "  may be necessary.",
        "",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
