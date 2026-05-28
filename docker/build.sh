#!/bin/bash
# Build IsaacLab-Arena + rosclaw-darwin Docker image.
# This script fixes apt/pip network issues for Chinese mainland users.
#
# Usage:
#   ./docker/build.sh                  # Build base image only
#   ./docker/build.sh --full           # Build base + rosclaw-darwin
#   ./docker/build.sh --rebuild        # Force rebuild without cache

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ISAACLAB_ARENA_DIR="${ISAACLAB_ARENA_DIR:-/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena}"

# Image names
BASE_IMAGE_TAG="rosclaw-darwin:arena-base"
FULL_IMAGE_TAG="rosclaw-darwin:latest"

# Build args
APT_MIRROR="${APT_MIRROR:-repo.huaweicloud.com}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_EXTRA_INDEX="${PIP_EXTRA_INDEX:-https://pypi.ngc.nvidia.com}"

# Parse args
REBUILD=false
BUILD_FULL=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --rebuild|-R) REBUILD=true; shift ;;
        --full|-f) BUILD_FULL=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "========================================"
echo "ROSClaw-Darwin Docker Build"
echo "========================================"
echo "APT mirror:    ${APT_MIRROR}"
echo "PIP index:     ${PIP_INDEX}"
echo "PIP extra:     ${PIP_EXTRA_INDEX}"
echo "Arena dir:     ${ISAACLAB_ARENA_DIR}"
echo "Rebuild:       ${REBUILD}"
echo "Build full:    ${BUILD_FULL}"
echo ""

# Check prerequisites
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker not found. Please install Docker first."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "ERROR: Docker daemon not running."
    exit 1
fi

# Check if NGC login is available
if ! docker pull --quiet nvcr.io/nvidia/isaac-sim:6.0.0-dev2 &>/dev/null 2>&1; then
    echo "WARNING: Cannot pull Isaac Sim base image. Make sure you are logged in to nvcr.io:"
    echo "  docker login nvcr.io"
fi

# Check Arena directory
if [[ ! -d "${ISAACLAB_ARENA_DIR}" ]]; then
    echo "ERROR: IsaacLab-Arena directory not found at ${ISAACLAB_ARENA_DIR}"
    echo "Download it first: git clone https://github.com/isaac-sim/IsaacLab-Arena"
    exit 1
fi

# Check submodules
if [[ ! -d "${ISAACLAB_ARENA_DIR}/submodules/IsaacLab/source" ]]; then
    echo "WARNING: IsaacLab submodule not initialized. Initializing..."
    (cd "${ISAACLAB_ARENA_DIR}" && \
        git config submodule.submodules/IsaacLab.url https://github.com/isaac-sim/IsaacLab.git && \
        git config submodule.submodules/Isaac-GR00T.url https://github.com/NVIDIA/Isaac-GR00T.git && \
        git submodule update --init --recursive --depth 1)
fi

echo ""
echo "[1/3] Patching IsaacLab-Arena Dockerfile..."

# Create a patched Dockerfile in the Arena directory
PATCHED_DOCKERFILE="${ISAACLAB_ARENA_DIR}/docker/Dockerfile.rosclaw"
cp "${ISAACLAB_ARENA_DIR}/docker/Dockerfile.isaaclab_arena" "${PATCHED_DOCKERFILE}"

# Fix apt sources - replace archive.ubuntu.com and security.ubuntu.com
sed -i "s|http://archive.ubuntu.com/ubuntu/|http://${APT_MIRROR}/ubuntu/|g" "${PATCHED_DOCKERFILE}"
sed -i "s|http://security.ubuntu.com/ubuntu/|http://${APT_MIRROR}/ubuntu/|g" "${PATCHED_DOCKERFILE}"

# Also fix any plain archive.ubuntu.com references (without protocol)
sed -i "s|archive.ubuntu.com|${APT_MIRROR}|g" "${PATCHED_DOCKERFILE}"
sed -i "s|security.ubuntu.com|${APT_MIRROR}|g" "${PATCHED_DOCKERFILE}"

# Fix apt-get to be more resilient to network issues
# Export vars for Python here-doc
export PATCHED_DOCKERFILE
export APT_MIRROR
python3 << 'PYEOF'
import re, os
PATCHED_DOCKERFILE = os.environ.get('PATCHED_DOCKERFILE', '/tmp/Dockerfile.rosclaw')
APT_MIRROR = os.environ.get('APT_MIRROR', 'mirrors.tuna.tsinghua.edu.cn')
with open(PATCHED_DOCKERFILE, 'r') as f:
    content = f.read()

# Insert full sources.list rewrite + apt hardening after 'USER root'
source_rewrite = f"""RUN rm -rf /var/lib/apt/lists/* /etc/apt/sources.list.d/* /tmp/* /var/tmp/* \\
    && echo "deb http://{APT_MIRROR}/ubuntu/ noble main restricted universe multiverse" > /etc/apt/sources.list \\
    && echo "deb http://{APT_MIRROR}/ubuntu/ noble-updates main restricted universe multiverse" >> /etc/apt/sources.list \\
    && echo "deb http://{APT_MIRROR}/ubuntu/ noble-security main restricted universe multiverse" >> /etc/apt/sources.list \\
    && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check \\
    && echo 'Acquire::AllowInsecureRepositories "true";' >> /etc/apt/apt.conf.d/99no-check \\
    && echo 'Acquire::AllowDowngradeToInsecureRepositories "true";' >> /etc/apt/apt.conf.d/99no-check \\
    && echo 'Acquire::Retries "3";' >> /etc/apt/apt.conf.d/99no-check \\
    && echo 'Acquire::http::Timeout "120";' >> /etc/apt/apt.conf.d/99no-check \\
    && apt-get clean \\
    && apt-get update --allow-insecure-repositories --allow-releaseinfo-change -y || true
ENV GIT_HTTP_LOW_SPEED_TIME=30 GIT_HTTP_LOW_SPEED_LIMIT=1000
"""
content = content.replace('USER root\n', 'USER root\n' + source_rewrite + '\n')

# Replace ALL apt-get/apt update + install lines to be more resilient
# Pattern 1: apt-get update && apt-get install -y
content = re.sub(
    r'RUN apt-get update && apt-get install -y',
    'RUN apt-get update --allow-insecure-repositories --allow-releaseinfo-change || true && apt-get install -y --no-install-recommends --allow-unauthenticated --fix-missing',
    content
)
# Pattern 2: apt update && apt install (used later in Dockerfile)
content = re.sub(
    r'apt update &&\\s*\\\n\\s*apt install',
    'apt-get update --allow-insecure-repositories --allow-releaseinfo-change || true && apt-get install -y --no-install-recommends --allow-unauthenticated --fix-missing',
    content
)
# Pattern 3: standalone apt-get update (e.g., before pipx install)
content = re.sub(
    r'RUN apt-get update && apt-get install -y',
    'RUN apt-get update --allow-insecure-repositories --allow-releaseinfo-change || true && apt-get install -y --no-install-recommends --allow-unauthenticated --fix-missing',
    content
)

# Fix missing isaaclab packages that may not exist in current IsaacLab version
# (isaaclab_visualizers and isaaclab_teleop were removed in newer IsaacLab)
content = content.replace(
    'RUN /isaac-sim/python.sh -m pip install --no-deps -e ${WORKDIR}/submodules/IsaacLab/source/isaaclab_visualizers',
    'RUN [ -d "${WORKDIR}/submodules/IsaacLab/source/isaaclab_visualizers" ] && /isaac-sim/python.sh -m pip install --no-deps -e "${WORKDIR}/submodules/IsaacLab/source/isaaclab_visualizers" || echo "Skipping isaaclab_visualizers (not found)"'
)
content = content.replace(
    'RUN /isaac-sim/python.sh -m pip install --no-deps -e ${WORKDIR}/submodules/IsaacLab/source/isaaclab_teleop',
    'RUN [ -d "${WORKDIR}/submodules/IsaacLab/source/isaaclab_teleop" ] && /isaac-sim/python.sh -m pip install --no-deps -e "${WORKDIR}/submodules/IsaacLab/source/isaaclab_teleop" || echo "Skipping isaaclab_teleop (not found)"'
)
# isaaclab_newton may also be missing - skip if not present
# Original spans two lines with backslash continuation
content = content.replace(
    'RUN /isaac-sim/python.sh -m pip install -e \\\n      "${WORKDIR}/submodules/IsaacLab/source/isaaclab_newton[all]"',
    'RUN [ -d "${WORKDIR}/submodules/IsaacLab/source/isaaclab_newton" ] && /isaac-sim/python.sh -m pip install -e "${WORKDIR}/submodules/IsaacLab/source/isaaclab_newton[all]" || echo "Skipping isaaclab_newton (not found)"'
)

# Isaac-GR00T submodule may be empty - skip install if not a valid Python project
content = content.replace(
    'RUN /isaac-sim/python.sh -m pip install msgpack==1.1.0 msgpack-numpy==0.4.8 pyzmq==27.0.1 && \\\n    /isaac-sim/python.sh -m pip install --no-deps --ignore-requires-python -e ${WORKDIR}/submodules/Isaac-GR00T/',
    'RUN /isaac-sim/python.sh -m pip install msgpack==1.1.0 msgpack-numpy==0.4.8 pyzmq==27.0.1 \\\n    && ([ -f "${WORKDIR}/submodules/Isaac-GR00T/setup.py" ] || [ -f "${WORKDIR}/submodules/Isaac-GR00T/pyproject.toml" ]) \\\n    && /isaac-sim/python.sh -m pip install --no-deps --ignore-requires-python -e "${WORKDIR}/submodules/Isaac-GR00T/" \\\n    || echo "Skipping Isaac-GR00T (not a Python project)"'
)

# openpi-client depends on GitHub submodules that hang in China - remove entirely
# Also remove the OPENPI_COMMIT COPY since it's only needed for openpi-client
content = content.replace(
    'COPY isaaclab_arena_openpi/docker/OPENPI_COMMIT /tmp/openpi_commit\n',
    '# Skipped: OPENPI_COMMIT only needed for openpi-client (GitHub network issues)\n'
)
content = content.replace(
    'RUN OPENPI_COMMIT=$(tr -d \'[:space:]\' < /tmp/openpi_commit) && \\\n    /isaac-sim/python.sh -m pip install --no-cache-dir \\\n    "openpi-client @ git+https://github.com/Physical-Intelligence/openpi@${OPENPI_COMMIT}#subdirectory=packages/openpi-client" && \\\n    rm /tmp/openpi_commit\n',
    '# Skipped: openpi-client requires GitHub submodules (network issues in China)\n'
)

# Replace wildcard COPY with explicit file list to avoid .claude/skills symlink conflict
content = content.replace(
    'COPY *.* ${WORKDIR}/',
    'COPY *.py *.toml *.cfg *.ini *.txt *.md *.json *.yaml *.yml *.sh ${WORKDIR}/'
)

# Fix pip compatibility before isaaclab.sh -i (Isaac Sim pip may conflict with apt python3-pip)
# Also install EGL dev libs needed by egl_probe (optional headless rendering detector)
content = content.replace(
    'RUN ${ISAACLAB_PATH}/isaaclab.sh -i',
    'RUN apt-get install -y --no-install-recommends libegl1-mesa-dev && /isaac-sim/python.sh -m pip install --upgrade pip packaging setuptools wheel && ${ISAACLAB_PATH}/isaaclab.sh -i || echo "isaaclab.sh completed with warnings"'
)

with open(PATCHED_DOCKERFILE, 'w') as f:
    f.write(content)
PYEOF

# Also fix remaining 'apt' calls (not apt-get) that weren't caught by regex above
sed -i 's#apt update#apt-get update --allow-insecure-repositories --allow-releaseinfo-change || true#g' "${PATCHED_DOCKERFILE}"
sed -i 's#apt install#apt-get install -y --no-install-recommends --allow-unauthenticated --fix-missing#g' "${PATCHED_DOCKERFILE}"

# Fix pip sources - configure pip to use Tsinghua mirror + NVIDIA NGC extra index
sed -i '/USER root/a\
# Configure pip to use Tsinghua mirror + NVIDIA NGC extra index\nRUN /isaac-sim/python.sh -m pip config set global.index-url '"${PIP_INDEX}"' 2>/dev/null || true\nRUN /isaac-sim/python.sh -m pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn pypi.ngc.nvidia.com pypi.org files.pythonhosted.org 2>/dev/null || true\nRUN /isaac-sim/python.sh -m pip config set global.extra-index-url '"${PIP_EXTRA_INDEX}"' 2>/dev/null || true' "${PATCHED_DOCKERFILE}"

# Patch Warp torch.py: add shortcut for PyTorch tensors (IsaacLab-Arena sometimes passes tensors to wp.to_torch)
WARP_PATCH='RUN for WARP_TORCH in /isaac-sim/kit/python/lib/python3.12/site-packages/warp/_src/torch.py /isaac-sim/extscache/omni.warp.core-*/warp/_src/torch.py; do \
    if [ -f "\$WARP_TORCH" ]; then \
        sed -i "/import torch  # noqa PLC0415/a\\\    if isinstance(a, torch.Tensor):\n        return a" "\$WARP_TORCH"; \
        echo "Patched \$WARP_TORCH"; \
    fi; \
done'
# Insert after isaaclab.sh -i line (which is near the end of package installs)
sed -i '/isaaclab.sh -i || echo/i\
# Patch Warp torch.py for PyTorch tensor passthrough\n'"${WARP_PATCH}"'' "${PATCHED_DOCKERFILE}"

echo "  Patched: ${PATCHED_DOCKERFILE}"

echo ""
echo "[2/3] Building base image: ${BASE_IMAGE_TAG}..."

BUILD_ARGS=()
if [[ "${REBUILD}" == "true" ]]; then
    BUILD_ARGS+=("--no-cache")
fi

cd "${ISAACLAB_ARENA_DIR}"
docker build \
    -f docker/Dockerfile.rosclaw \
    -t "${BASE_IMAGE_TAG}" \
    "${BUILD_ARGS[@]}" \
    . 2>&1 | tee "${PROJECT_ROOT}/docker/build-base.log"

BUILD_EXIT=${PIPESTATUS[0]}
if [[ ${BUILD_EXIT} -ne 0 ]]; then
    echo ""
    echo "ERROR: Base image build failed (exit ${BUILD_EXIT})"
    echo "Check log: ${PROJECT_ROOT}/docker/build-base.log"
    exit 1
fi

echo ""
echo "  Base image built: ${BASE_IMAGE_TAG}"

# Clean up patched Dockerfile
rm -f "${PATCHED_DOCKERFILE}"

# Build full rosclaw-darwin image if requested
if [[ "${BUILD_FULL}" == "true" ]]; then
    echo ""
    echo "[3/3] Building full image: ${FULL_IMAGE_TAG}..."

    cd "${PROJECT_ROOT}"
    docker build \
        -f docker/Dockerfile \
        -t "${FULL_IMAGE_TAG}" \
        --build-arg BASE_IMAGE="${BASE_IMAGE_TAG}" \
        "${BUILD_ARGS[@]}" \
        . 2>&1 | tee "${PROJECT_ROOT}/docker/build-full.log"

    BUILD_EXIT=${PIPESTATUS[0]}
    if [[ ${BUILD_EXIT} -ne 0 ]]; then
        echo ""
        echo "ERROR: Full image build failed (exit ${BUILD_EXIT})"
        echo "Check log: ${PROJECT_ROOT}/docker/build-full.log"
        exit 1
    fi

    echo ""
    echo "  Full image built: ${FULL_IMAGE_TAG}"
fi

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"
echo ""
echo "Images:"
docker images | grep "rosclaw-darwin"
echo ""
echo "Usage:"
if [[ "${BUILD_FULL}" == "true" ]]; then
    echo "  make run              # Run rosclaw-darwin with full integration"
    echo "  make demo             # Run end-to-end demo"
else
    echo "  ./docker/build.sh --full    # Build full rosclaw-darwin image"
fi
echo ""
