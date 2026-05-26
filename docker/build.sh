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
APT_MIRROR="${APT_MIRROR:-mirrors.aliyun.com}"
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
# Use Python for reliable multi-line replacement
python3 -c "
import re
with open('${PATCHED_DOCKERFILE}', 'r') as f:
    content = f.read()
# Replace apt-get update line
content = re.sub(
    r'RUN apt-get update && apt-get install -y',
    'RUN apt-get update --fix-missing || true && apt-get install -y --fix-missing --allow-unauthenticated',
    content
)
with open('${PATCHED_DOCKERFILE}', 'w') as f:
    f.write(content)
"

# Fix pip sources - configure pip to use Tsinghua mirror + NVIDIA NGC extra index
sed -i '/USER root/a\
# Configure pip to use Tsinghua mirror + NVIDIA NGC extra index\nRUN /isaac-sim/python.sh -m pip config set global.index-url '"${PIP_INDEX}"' 2>/dev/null || true\nRUN /isaac-sim/python.sh -m pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || true\nRUN /isaac-sim/python.sh -m pip config set global.extra-index-url '"${PIP_EXTRA_INDEX}"' 2>/dev/null || true' "${PATCHED_DOCKERFILE}"

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
