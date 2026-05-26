"""Minimal EEIB Dashboard using FastAPI.

Serves a JSON API for leaderboard data and a static HTML page
that renders the EEIB leaderboard with SDR / MIE / SSI metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


@dataclass
class LeaderboardEntry:
    agent_name: str
    model: str
    sdr: float = 0.0  # Skill Discovery Rate
    mie: float = 0.0  # Memory Integration Efficiency
    ssi: float = 0.0  # Swarm Synergy Index
    evolution_score: float = 0.0
    tasks_evaluated: int = 0
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class DashboardApp:
    """FastAPI-based EEIB leaderboard dashboard."""

    def __init__(self, data_dir: str | None = None):
        self.app = FastAPI(title="ROSClaw-Darwin EEIB", version="0.1.0")
        self.entries: list[LeaderboardEntry] = []
        self.data_dir = Path(data_dir) if data_dir else Path.cwd() / "darwin_results"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._setup_routes()
        self._load_existing()

    def _setup_routes(self) -> None:
        @self.app.get("/", response_class=HTMLResponse)
        async def index() -> str:
            return self._render_html()

        @self.app.get("/api/leaderboard")
        async def get_leaderboard() -> JSONResponse:
            return JSONResponse(
                content={
                    "entries": [
                        {
                            "agent_name": e.agent_name,
                            "model": e.model,
                            "sdr": round(e.sdr, 4),
                            "mie": round(e.mie, 4),
                            "ssi": round(e.ssi, 4),
                            "evolution_score": round(e.evolution_score, 4),
                            "tasks_evaluated": e.tasks_evaluated,
                            "timestamp": e.timestamp,
                        }
                        for e in sorted(self.entries, key=lambda x: x.evolution_score, reverse=True)
                    ]
                }
            )

        @self.app.post("/api/submit")
        async def submit_result(data: dict[str, Any]) -> JSONResponse:
            entry = LeaderboardEntry(
                agent_name=data.get("agent_name", "unknown"),
                model=data.get("model", "unknown"),
                sdr=data.get("sdr", 0.0),
                mie=data.get("mie", 0.0),
                ssi=data.get("ssi", 0.0),
                evolution_score=data.get("evolution_score", 0.0),
                tasks_evaluated=data.get("tasks_evaluated", 0),
                timestamp=data.get("timestamp", ""),
                metadata=data.get("metadata", {}),
            )
            self.entries.append(entry)
            self._persist(entry)
            return JSONResponse(content={"status": "ok", "rank": len(self.entries)})

        @self.app.get("/api/evolution/{task_id}")
        async def get_evolution(task_id: str) -> JSONResponse:
            path = self.data_dir / f"{task_id}.json"
            if not path.exists():
                return JSONResponse(content={"error": "not found"}, status_code=404)
            return JSONResponse(content=json.loads(path.read_text()))

    def _render_html(self) -> str:
        return """
<!DOCTYPE html>
<html>
<head>
    <title>ROSClaw-Darwin EEIB Leaderboard</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 1200px; margin: 0 auto; padding: 2rem; }
        h1 { color: #1a1a2e; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #16213e; color: white; }
        tr:hover { background: #f5f5f5; }
        .metric { font-family: monospace; font-weight: bold; }
        .rank-1 { background: #ffd700 !important; }
        .rank-2 { background: #c0c0c0 !important; }
        .rank-3 { background: #cd7f32 !important; }
        .subtitle { color: #666; margin-top: -0.5rem; }
    </style>
</head>
<body>
    <h1>🏆 ROSClaw-Darwin EEIB Leaderboard</h1>
    <p class="subtitle">Evolutionary Embodied Intelligence Benchmark — measuring how fast agents evolve, not how strong they are.</p>
    <div id="content">Loading...</div>
    <script>
        async function load() {
            const res = await fetch('/api/leaderboard');
            const data = await res.json();
            const entries = data.entries;
            if (entries.length === 0) {
                document.getElementById('content').innerHTML = '<p>No submissions yet. Run an evolution evaluation to populate the leaderboard.</p>';
                return;
            }
            let html = '<table><tr><th>Rank</th><th>Agent</th><th>Model</th><th>Evolution Score</th><th>SDR</th><th>MIE</th><th>SSI</th><th>Tasks</th><th>Timestamp</th></tr>';
            entries.forEach((e, i) => {
                const cls = i < 3 ? `rank-${i+1}` : '';
                html += `<tr class="${cls}"><td>#${i+1}</td><td>${e.agent_name}</td><td>${e.model}</td><td class="metric">${e.evolution_score}</td><td class="metric">${e.sdr}</td><td class="metric">${e.mie}</td><td class="metric">${e.ssi}</td><td>${e.tasks_evaluated}</td><td>${e.timestamp}</td></tr>`;
            });
            html += '</table>';
            document.getElementById('content').innerHTML = html;
        }
        load();
    </script>
</body>
</html>
        """

    def _persist(self, entry: LeaderboardEntry) -> None:
        path = self.data_dir / f"entry_{entry.agent_name}_{entry.timestamp}.json"
        path.write_text(
            json.dumps(
                {
                    "agent_name": entry.agent_name,
                    "model": entry.model,
                    "sdr": entry.sdr,
                    "mie": entry.mie,
                    "ssi": entry.ssi,
                    "evolution_score": entry.evolution_score,
                    "tasks_evaluated": entry.tasks_evaluated,
                    "timestamp": entry.timestamp,
                    "metadata": entry.metadata,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _load_existing(self) -> None:
        for path in self.data_dir.glob("entry_*.json"):
            try:
                data = json.loads(path.read_text())
                self.entries.append(LeaderboardEntry(**data))
            except Exception:
                pass

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        import uvicorn

        uvicorn.run(self.app, host=host, port=port)
