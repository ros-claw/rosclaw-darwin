# ROSClaw-Darwin Docker Image
# Built on top of IsaacLab-Arena base image.
#
# This Dockerfile adds rosclaw-darwin and its ecosystem integration
# to the pre-built IsaacLab-Arena environment.
#
# Usage:
#   docker build -f docker/Dockerfile -t rosclaw-darwin:latest .
#   docker run --gpus all --rm -it rosclaw-darwin:latest

ARG BASE_IMAGE=rosclaw-darwin:arena-base

FROM ${BASE_IMAGE}

USER root

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------
ENV WORKDIR=/workspace
ENV ROSCLAW_DARWIN_PATH=/workspace/rosclaw-darwin
ENV PYTHONPATH="${ROSCLAW_DARWIN_PATH}:${PYTHONPATH}"
ENV ROSCLAW_PRACTICE_MCAP_DIR=/data/rosclaw/mcap
ENV ROSCLAW_PRACTICE_FALLBACK_DIR=/data/rosclaw/fallback
ENV SEEKDB_MODE=embedded
ENV SEEKDB_PATH=/data/seekdb/darwin

# -----------------------------------------------------------------------------
# Install rosclaw-darwin
# -----------------------------------------------------------------------------
WORKDIR ${WORKDIR}

# Copy rosclaw-darwin source
COPY . ${ROSCLAW_DARWIN_PATH}

# Install rosclaw-darwin package
RUN /isaac-sim/python.sh -m pip install -e "${ROSCLAW_DARWIN_PATH}"

# Install dashboard dependencies if needed
RUN /isaac-sim/python.sh -m pip install fastapi uvicorn

# Create data directories
RUN mkdir -p /data/rosclaw/mcap /data/rosclaw/fallback /data/seekdb/darwin

# -----------------------------------------------------------------------------
# Install rosclaw ecosystem (optional, for full integration)
# -----------------------------------------------------------------------------
# These are installed from the local ros-claw repos if available.
# If not available, the bridges gracefully fall back to mock mode.

# Install rosclaw-practice
RUN if [ -d /workspace/rosclaw-practice ]; then \
        /isaac-sim/python.sh -m pip install -e /workspace/rosclaw-practice; \
    fi

# Install rosclaw-memory
RUN if [ -d /workspace/rosclaw-memory ]; then \
        /isaac-sim/python.sh -m pip install -e /workspace/rosclaw-memory; \
    fi

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
COPY docker/entrypoint.sh /rosclaw-entrypoint.sh
RUN chmod +x /rosclaw-entrypoint.sh

WORKDIR ${ROSCLAW_DARWIN_PATH}

ENTRYPOINT ["/rosclaw-entrypoint.sh"]
CMD ["/bin/bash"]
