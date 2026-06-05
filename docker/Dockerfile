# ROSClaw-Darwin Dockerfile
# Multi-stage: mock-dev | arena-dev | full

FROM python:3.10-slim AS base
WORKDIR /workspace/rosclaw-darwin
COPY pyproject.toml README.md ./
COPY rosclaw_darwin/ ./rosclaw_darwin/
RUN pip install --no-cache-dir -e ".[dev]"

# --- mock-dev target ---
FROM base AS mock
COPY examples/ ./examples/
COPY configs/ ./configs/
COPY tests/ ./tests/
CMD ["darwin", "dashboard", "--host", "0.0.0.0", "--port", "8080"]

# --- arena-dev target ---
FROM nvcr.io/nvidia/isaac-sim:4.2.0 AS arena
WORKDIR /workspace/rosclaw-darwin
COPY --from=base /workspace/rosclaw-darwin /workspace/rosclaw-darwin
COPY examples/ ./examples/
COPY configs/ ./configs/
ENV ROSCLAW_ARENA_MODE=real
CMD ["tail", "-f", "/dev/null"]

# --- full target (placeholder) ---
FROM arena AS full
# Additional heavy dependencies (LW-BenchHub, RoboTwin) mounted at runtime
ENV ROSCLAW_ARENA_MODE=real
CMD ["tail", "-f", "/dev/null"]
