"""Static SVG chart generation for the ROSClaw-Darwin dashboard.

This module intentionally avoids external plotting dependencies (matplotlib is
not in the base environment).  It produces lightweight, embeddable SVG strings
that can be served directly by FastAPI and rendered by any browser.
"""

from __future__ import annotations

import math
from typing import Any


def _svg_start(width: int, height: int, title: str = "") -> str:
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title}">\n'
    )
    if title:
        head += f'  <title>{title}</title>\n'
    head += f'  <rect width="{width}" height="{height}" fill="#ffffff"/>\n'
    return head


def _svg_end() -> str:
    return "</svg>\n"


def _text(x: float, y: float, content: str, *, anchor: str = "start", size: int = 12, color: str = "#212529", rotate: int = 0) -> str:
    transform = f' transform="rotate({rotate},{x},{y})"' if rotate else ""
    return (
        f'  <text x="{x:.1f}" y="{y:.1f}" font-size="{size}px" fill="{color}" '
        f'text-anchor="{anchor}"{transform}>{content}</text>\n'
    )


def _line(x1: float, y1: float, x2: float, y2: float, color: str = "#adb5bd", width: float = 1) -> str:
    return (
        f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{color}" stroke-width="{width}"/>\n'
    )


def _rect(x: float, y: float, w: float, h: float, fill: str, stroke: str | None = None, rx: float = 0) -> str:
    s = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" rx="{rx}"{s}/>\n'


def _polyline(points: list[tuple[float, float]], color: str = "#0b7285", width: float = 2) -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'  <polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>\n'


def _bar_color(index: int) -> str:
    palette = ["#0b7285", "#2b8a3e", "#e67700", "#c92a2a", "#5f3dc4", "#1864ab", "#862e9c"]
    return palette[index % len(palette)]


def _nice_ticks(min_v: float, max_v: float, n: int = 5) -> list[float]:
    if not math.isfinite(min_v) or not math.isfinite(max_v) or max_v <= min_v:
        return [0.0, 1.0]
    span = max_v - min_v
    step = 10 ** math.floor(math.log10(span / n))
    if span / step / n < 2:
        step *= 0.5
    elif span / step / n >= 5:
        step *= 2
    start = math.floor(min_v / step) * step
    ticks = []
    while start <= max_v:
        ticks.append(start)
        start += step
    return ticks


def plot_lift_progress(run: dict[str, Any], width: int = 900, height: int = 360) -> str:
    """SVG bar/scatter summary of per-episode lift progress metrics.

    Plots three episode-level series: progress, object_height_delta, and
    eef_to_object_distance_min.  This is the most useful view given the
    aggregated ``episode_metrics`` stored in run artifacts.
    """
    episodes = run.get("episode_metrics") or []
    if not episodes:
        return _svg_start(width, height, "No lift data") + _text(width / 2, height / 2, "No episode data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 50, "right": 140, "bottom": 60, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    title = f"{run.get('task_id', 'task')} / {run.get('policy_id', 'policy')} ({len(episodes)} episodes)"
    svg = _svg_start(width, height, title)
    svg += _text(width / 2, 24, title, anchor="middle", size=14, color="#1a1a2e")

    n = len(episodes)
    bar_w = max(4, plot_w / max(n, 1) * 0.6)
    spacing = plot_w / max(n, 1)

    progress_vals = [float(ep.get("progress", 0.0) or 0.0) for ep in episodes]
    height_vals = [float(ep.get("object_height_delta", 0.0) or 0.0) for ep in episodes]
    dist_vals = [float(ep.get("eef_to_object_distance_min", 1.0) or 1.0) for ep in episodes]

    # Normalize to shared 0..1 y-axis for compact visualization.
    max_h = max(0.25, max(height_vals))
    max_d = max(0.5, max(dist_vals))

    def y(v: float, scale: float) -> float:
        return margin["top"] + plot_h - v / scale * plot_h

    for i, (p, h, d) in enumerate(zip(progress_vals, height_vals, dist_vals)):
        x = margin["left"] + i * spacing + spacing / 2
        # progress as top portion of a vertical bar
        ph = max(1, p * plot_h)
        svg += _rect(x - bar_w / 2, margin["top"] + plot_h - ph, bar_w, ph, "#d3f9d8", stroke="#2b8a3e")
        # object height delta as a diamond marker
        hy = y(h, max_h)
        svg += f'  <polygon points="{x:.1f},{hy - 4:.1f} {x + 4:.1f},{hy:.1f} {x:.1f},{hy + 4:.1f} {x - 4:.1f},{hy:.1f}" fill="#e67700"/>\n'
        # distance as a small horizontal tick
        dy = y(d, max_d)
        svg += _line(x - bar_w / 2, dy, x + bar_w / 2, dy, "#0b7285", 2)

    # Axes
    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)

    # Y ticks (progress scale)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    svg += _text(18, height / 2, "progress / height / distance", anchor="middle", size=11, color="#495057", rotate=270)
    svg += _text(margin["left"] + plot_w / 2, height - 18, "episode index", anchor="middle", size=11, color="#495057")

    # Legend
    lx = margin["left"] + plot_w + 20
    ly = margin["top"] + 20
    svg += _rect(lx, ly, 12, 12, "#d3f9d8", stroke="#2b8a3e")
    svg += _text(lx + 18, ly + 10, "progress", size=10)
    svg += f'  <polygon points="{lx + 6:.1f},{ly + 30 - 4:.1f} {lx + 10:.1f},{ly + 30:.1f} {lx + 6:.1f},{ly + 30 + 4:.1f} {lx + 2:.1f},{ly + 30:.1f}" fill="#e67700"/>\n'
    svg += _text(lx + 18, ly + 32, "height Δ", size=10)
    svg += _line(lx, ly + 50, lx + 12, ly + 50, "#0b7285", 2)
    svg += _text(lx + 18, ly + 53, "eef min", size=10)

    svg += _svg_end()
    return svg


def plot_ablations(ablations: list[dict[str, Any]], width: int = 800, height: int = 400) -> str:
    """Grouped bar chart comparing success_rate and progress across ablations."""
    if not ablations:
        return _svg_start(width, height, "No ablations") + _text(width / 2, height / 2, "No ablation data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 50, "right": 140, "bottom": 80, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Skill hint ablations")
    svg += _text(width / 2, 24, "Skill Hint Ablations: success rate and progress", anchor="middle", size=14, color="#1a1a2e")

    n = len(ablations)
    group_w = plot_w / n
    bar_w = group_w * 0.22
    labels = ["no hint", "manual", "auto"]

    for i, ab in enumerate(ablations):
        gx = margin["left"] + i * group_w
        vals = [
            float(ab.get("without_hints_sr", 0.0) or 0.0),
            float(ab.get("manual_hints_sr", 0.0) or 0.0),
            float(ab.get("with_auto_hints_sr", 0.0) or 0.0),
        ]
        prog_vals = [
            float(ab.get("without_hints_progress", 0.0) or 0.0),
            float(ab.get("manual_hints_progress", 0.0) or 0.0),
            float(ab.get("with_auto_hints_progress", 0.0) or 0.0),
        ]
        for j, (sr, pr) in enumerate(zip(vals, prog_vals)):
            x = gx + group_w * 0.15 + j * (bar_w + 4)
            # success rate bar
            h_sr = max(1, sr * plot_h)
            svg += _rect(x, margin["top"] + plot_h - h_sr, bar_w, h_sr, _bar_color(j), rx=2)
            # progress overlay (narrower, slightly darker)
            h_pr = max(1, pr * plot_h)
            svg += _rect(x + bar_w * 0.25, margin["top"] + plot_h - h_pr, bar_w * 0.5, h_pr, "#495057", rx=1)

        # x-axis label
        label = ab.get("task_id", f"#{i}")
        svg += _text(gx + group_w / 2, margin["top"] + plot_h + 20, label, anchor="middle", size=10, color="#495057", rotate=30)

    # Axes and ticks
    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    # Legend
    lx = margin["left"] + plot_w + 20
    ly = margin["top"] + 20
    for j, label in enumerate(labels):
        svg += _rect(lx, ly + j * 22, 12, 12, _bar_color(j), rx=2)
        svg += _text(lx + 18, ly + j * 22 + 10, f"{label} SR", size=10)
    svg += _rect(lx, ly + len(labels) * 22, 12, 12, "#495057", rx=1)
    svg += _text(lx + 18, ly + len(labels) * 22 + 10, "progress", size=10)

    svg += _svg_end()
    return svg


def plot_failure_signature_distribution(runs: list[dict[str, Any]], width: int = 800, height: int = 360) -> str:
    """Stacked bar chart of failure_type counts across runs."""
    counts: dict[str, int] = {}
    for run in runs:
        for ft, c in (run.get("failure_counts") or {}).items():
            counts[ft] = counts.get(ft, 0) + int(c or 0)
    if not counts:
        return _svg_start(width, height, "No failures") + _text(width / 2, height / 2, "No failure data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 40, "right": 40, "bottom": 120, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Failure distribution")
    svg += _text(width / 2, 24, "Failure-type distribution across runs", anchor="middle", size=14, color="#1a1a2e")

    labels = list(counts.keys())
    values = [counts[k] for k in labels]
    max_v = max(values) if values else 1

    bar_w = min(60, plot_w / max(len(labels), 1) * 0.6)
    spacing = plot_w / max(len(labels), 1)

    for i, (label, val) in enumerate(zip(labels, values)):
        x = margin["left"] + i * spacing + spacing / 2 - bar_w / 2
        h = val / max_v * plot_h
        svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, _bar_color(i), rx=2)
        svg += _text(x + bar_w / 2, margin["top"] + plot_h - h - 6, str(val), anchor="middle", size=10, color="#212529")
        # rotated x label
        svg += _text(x + bar_w / 2, margin["top"] + plot_h + 18, label, anchor="end", size=10, color="#495057", rotate=45)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    ticks = _nice_ticks(0, max_v)
    for t in ticks:
        ty = margin["top"] + plot_h - t / max_v * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{int(t)}", anchor="end", size=10, color="#495057")

    svg += _svg_end()
    return svg


def plot_official_benchmark(success_rate: float, failure_distribution: dict[str, int], width: int = 800, height: int = 320) -> str:
    """Bar chart of failure distribution plus a text metric for the official benchmark."""
    if not failure_distribution:
        return _svg_start(width, height, "No benchmark data") + _text(width / 2, height / 2, "No benchmark data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 60, "right": 40, "bottom": 100, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Official benchmark")
    svg += _text(width / 2, 24, f"Official Benchmark — success rate {success_rate:.1%}", anchor="middle", size=14, color="#1a1a2e")

    labels = list(failure_distribution.keys())
    values = [failure_distribution[k] for k in labels]
    max_v = max(values) if values else 1

    bar_w = min(60, plot_w / max(len(labels), 1) * 0.6)
    spacing = plot_w / max(len(labels), 1)

    for i, (label, val) in enumerate(zip(labels, values)):
        x = margin["left"] + i * spacing + spacing / 2 - bar_w / 2
        h = val / max_v * plot_h if max_v else 0
        svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, _bar_color(i), rx=2)
        svg += _text(x + bar_w / 2, margin["top"] + plot_h - h - 6, str(val), anchor="middle", size=10, color="#212529")
        svg += _text(x + bar_w / 2, margin["top"] + plot_h + 18, label, anchor="end", size=10, color="#495057", rotate=45)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    ticks = _nice_ticks(0, max_v)
    for t in ticks:
        ty = margin["top"] + plot_h - t / max_v * plot_h if max_v else margin["top"] + plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{int(t)}", anchor="end", size=10, color="#495057")

    svg += _svg_end()
    return svg


def plot_target_yaw_matrix(per_target_yaw: dict[str, dict[str, float]], width: int = 900, height: int = 400) -> str:
    """Grouped bars for lifted_rate / orientation_achieved_rate / env_success_rate per target yaw."""
    if not per_target_yaw:
        return _svg_start(width, height, "No target yaw data") + _text(width / 2, height / 2, "No target yaw data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 60, "right": 140, "bottom": 80, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Target yaw matrix")
    svg += _text(width / 2, 24, "Target Yaw Generalization Matrix", anchor="middle", size=14, color="#1a1a2e")

    yaws = sorted(per_target_yaw.keys(), key=lambda k: float(k) if k.replace(".", "", 1).replace("-", "", 1).isdigit() else k)
    n = len(yaws)
    group_w = plot_w / n
    bar_w = group_w * 0.22
    metrics = ["lifted_rate", "orientation_achieved_rate", "env_success_rate"]
    metric_labels = ["lifted", "orient", "env succ"]

    for i, yaw in enumerate(yaws):
        gx = margin["left"] + i * group_w
        data = per_target_yaw.get(yaw, {})
        for j, metric in enumerate(metrics):
            val = float(data.get(metric, 0.0) or 0.0)
            x = gx + group_w * 0.15 + j * (bar_w + 4)
            h = max(1, val * plot_h)
            svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, _bar_color(j), rx=2)
        svg += _text(gx + group_w / 2, margin["top"] + plot_h + 20, yaw, anchor="middle", size=10, color="#495057", rotate=30)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    lx = margin["left"] + plot_w + 20
    ly = margin["top"] + 20
    for j, label in enumerate(metric_labels):
        svg += _rect(lx, ly + j * 22, 12, 12, _bar_color(j), rx=2)
        svg += _text(lx + 18, ly + j * 22 + 10, label, size=10)

    svg += _svg_end()
    return svg


def plot_ood_adaption(conditions: dict[str, dict[str, float]], width: int = 800, height: int = 320) -> str:
    """Grouped bars for success_rate per OOD condition."""
    if not conditions:
        return _svg_start(width, height, "No OOD data") + _text(width / 2, height / 2, "No OOD data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 60, "right": 40, "bottom": 100, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "OOD adaptation")
    svg += _text(width / 2, 24, "OOD Adaptation — Success Rate by Condition", anchor="middle", size=14, color="#1a1a2e")

    labels = sorted(conditions.keys())
    n = len(labels)
    group_w = plot_w / n
    bar_w = group_w * 0.5

    for i, label in enumerate(labels):
        gx = margin["left"] + i * group_w
        val = float(conditions[label].get("success_rate", 0.0) or 0.0)
        x = gx + group_w / 2 - bar_w / 2
        h = max(1, val * plot_h)
        svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, _bar_color(i), rx=2)
        svg += _text(x + bar_w / 2, margin["top"] + plot_h - h - 6, f"{val:.2f}", anchor="middle", size=10, color="#212529")
        svg += _text(x + bar_w / 2, margin["top"] + plot_h + 18, label, anchor="end", size=10, color="#495057", rotate=45)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    svg += _svg_end()
    return svg


def plot_failure_boundary(fba_result: dict[str, Any] | None = None, phase_scores: dict[str, float] | None = None, width: int = 800, height: int = 320) -> str:
    """Simple bar/number display for failure boundary analysis."""
    scores = phase_scores or {}
    if fba_result and not scores:
        scores = fba_result.get("phase_scores", {})
    if not scores:
        return _svg_start(width, height, "No failure boundary data") + _text(width / 2, height / 2, "No failure boundary data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 60, "right": 40, "bottom": 100, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Failure boundary")
    svg += _text(width / 2, 24, "Failure Boundary Analysis", anchor="middle", size=14, color="#1a1a2e")

    labels = sorted(scores.keys())
    values = [float(scores[k] or 0.0) for k in labels]
    max_v = max(max(values, default=1), 1.0)

    n = len(labels)
    bar_w = min(60, plot_w / max(n, 1) * 0.6)
    spacing = plot_w / max(n, 1)

    for i, (label, val) in enumerate(zip(labels, values)):
        x = margin["left"] + i * spacing + spacing / 2 - bar_w / 2
        h = val / max_v * plot_h
        svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, _bar_color(i), rx=2)
        svg += _text(x + bar_w / 2, margin["top"] + plot_h - h - 6, f"{val:.3f}", anchor="middle", size=10, color="#212529")
        svg += _text(x + bar_w / 2, margin["top"] + plot_h + 18, label, anchor="end", size=10, color="#495057", rotate=45)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    ticks = _nice_ticks(0, max_v)
    for t in ticks:
        ty = margin["top"] + plot_h - t / max_v * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    svg += _svg_end()
    return svg


def plot_transfer_matrix(ablations: list[dict[str, Any]], width: int = 700, height: int = 320) -> str:
    """Heatmap of skill-transfer gain (auto - no hint) per task."""
    if not ablations:
        return _svg_start(width, height, "No transfer data") + _text(width / 2, height / 2, "No transfer data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 50, "right": 140, "bottom": 60, "left": 160}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Cross-task transfer")
    svg += _text(width / 2, 24, "Cross-task skill-transfer gain (auto hints)", anchor="middle", size=14, color="#1a1a2e")

    gains = [float(ab.get("skill_transfer_gain", 0.0) or 0.0) for ab in ablations]
    max_abs = max(abs(g) for g in gains) or 1.0

    row_h = plot_h / len(ablations)
    for i, ab in enumerate(ablations):
        y = margin["top"] + i * row_h
        g = gains[i]
        # normalized color: red for negative, green for positive
        intensity = min(1.0, abs(g) / max_abs)
        if g >= 0:
            fill = f"rgba(43,138,62,{0.15 + intensity * 0.65})"
            text_color = "#2b8a3e"
        else:
            fill = f"rgba(201,42,42,{0.15 + intensity * 0.65})"
            text_color = "#c92a2a"
        svg += _rect(margin["left"], y, plot_w, row_h - 4, fill, rx=2)
        svg += _text(margin["left"] + 8, y + row_h / 2 + 4, ab.get("task_id", "task"), size=11, color="#212529")
        svg += _text(margin["left"] + plot_w - 8, y + row_h / 2 + 4, f"{g:+.3f}", anchor="end", size=12, color=text_color)

    # Legend bar
    lx = margin["left"] + plot_w + 20
    ly = margin["top"]
    for k in range(10):
        t = (k - 5) / 5.0
        intensity = abs(t)
        fill = f"rgba(43,138,62,{0.2 + intensity * 0.6})" if t >= 0 else f"rgba(201,42,42,{0.2 + intensity * 0.6})"
        svg += _rect(lx, ly + (9 - k) * (plot_h / 10), 16, plot_h / 10 - 1, fill)
    svg += _text(lx + 22, ly + 8, f"+{max_abs:.2f}", size=9, color="#2b8a3e")
    svg += _text(lx + 22, ly + plot_h - 4, f"-{max_abs:.2f}", size=9, color="#c92a2a")

    svg += _svg_end()
    return svg


def plot_procedural_validity(summary: dict[str, Any], width: int = 800, height: int = 320) -> str:
    """Bar chart of procedural object validity rates per task."""
    if not summary:
        return _svg_start(width, height, "No procedural validity data") + _text(width / 2, height / 2, "No procedural validity data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 60, "right": 40, "bottom": 100, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Procedural object validity")
    svg += _text(width / 2, 24, "Procedural Object Validity Audit", anchor="middle", size=14, color="#1a1a2e")

    labels = list(summary.keys())
    values = [summary[k].get("valid_rate", 0.0) or 0.0 for k in labels]
    n = len(labels)
    bar_w = min(80, plot_w / max(n, 1) * 0.6)
    spacing = plot_w / max(n, 1)

    for i, (label, val) in enumerate(zip(labels, values)):
        x = margin["left"] + i * spacing + spacing / 2 - bar_w / 2
        h = max(1, val * plot_h)
        fill = "#2b8a3e" if val >= 1.0 else ("#e67700" if val > 0.0 else "#c92a2a")
        svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, fill, rx=2)
        svg += _text(x + bar_w / 2, margin["top"] + plot_h - h - 6, f"{val:.2f}", anchor="middle", size=10, color="#212529")
        svg += _text(x + bar_w / 2, margin["top"] + plot_h + 18, label, anchor="end", size=10, color="#495057", rotate=45)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    svg += _svg_end()
    return svg


def plot_large_yaw_slip(per_yaw: dict[str, dict[str, Any]], width: int = 900, height: int = 400) -> str:
    """Grouped bars for lifted / orientation_achieved / env_success per target yaw plus category distribution."""
    if not per_yaw:
        return _svg_start(width, height, "No large yaw data") + _text(width / 2, height / 2, "No large yaw data", anchor="middle", size=14) + _svg_end()

    margin = {"top": 60, "right": 140, "bottom": 80, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Large yaw slip diagnosis")
    svg += _text(width / 2, 24, "Large-Yaw Slip Diagnosis", anchor="middle", size=14, color="#1a1a2e")

    yaws = sorted(per_yaw.keys())
    n = len(yaws)
    group_w = plot_w / n
    bar_w = group_w * 0.22
    metrics = ["lifted_rate", "orientation_achieved_rate", "env_success_rate"]
    metric_labels = ["lifted", "orient", "env succ"]

    for i, yaw in enumerate(yaws):
        gx = margin["left"] + i * group_w
        data = per_yaw.get(yaw, {})
        for j, metric in enumerate(metrics):
            val = float(data.get(metric, 0.0) or 0.0)
            x = gx + group_w * 0.15 + j * (bar_w + 4)
            h = max(1, val * plot_h)
            svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, _bar_color(j), rx=2)
        svg += _text(gx + group_w / 2, margin["top"] + plot_h + 20, yaw, anchor="middle", size=10, color="#495057", rotate=30)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    lx = margin["left"] + plot_w + 20
    ly = margin["top"] + 20
    for j, label in enumerate(metric_labels):
        svg += _rect(lx, ly + j * 22, 12, 12, _bar_color(j), rx=2)
        svg += _text(lx + 18, ly + j * 22 + 10, label, size=10)

    svg += _svg_end()
    return svg


def plot_official_post_reachability(
    old_success_rate: float,
    regression_success_rate: float | None,
    new_success_rate: float | None,
    width: int = 800,
    height: int = 320,
) -> str:
    """Bar chart comparing old, regression, and post-reachability official scores."""
    margin = {"top": 60, "right": 40, "bottom": 80, "left": 60}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    svg = _svg_start(width, height, "Official post-reachability benchmark")
    svg += _text(width / 2, 24, "Official Benchmark Score Trajectory", anchor="middle", size=14, color="#1a1a2e")

    labels = ["old 100-seed", "50-seed regression", "post-reachability 100-seed"]
    values = [old_success_rate, regression_success_rate, new_success_rate]
    colors = ["#0b7285", "#5f3dc4", "#2b8a3e"]
    n = len(labels)
    bar_w = min(80, plot_w / n * 0.6)
    spacing = plot_w / n

    for i, (label, val, color) in enumerate(zip(labels, values, colors)):
        x = margin["left"] + i * spacing + spacing / 2 - bar_w / 2
        h = max(1, (val or 0.0) * plot_h)
        svg += _rect(x, margin["top"] + plot_h - h, bar_w, h, color, rx=2)
        text = f"{val:.2f}" if val is not None else "pending"
        svg += _text(x + bar_w / 2, margin["top"] + plot_h - h - 6, text, anchor="middle", size=10, color="#212529")
        svg += _text(x + bar_w / 2, margin["top"] + plot_h + 18, label, anchor="end", size=10, color="#495057", rotate=30)

    svg += _line(margin["left"], margin["top"], margin["left"], margin["top"] + plot_h)
    svg += _line(margin["left"], margin["top"] + plot_h, margin["left"] + plot_w, margin["top"] + plot_h)
    for t in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ty = margin["top"] + plot_h - t * plot_h
        svg += _line(margin["left"] - 4, ty, margin["left"], ty, width=1)
        svg += _text(margin["left"] - 8, ty + 4, f"{t:.2f}", anchor="end", size=10, color="#495057")

    svg += _svg_end()
    return svg