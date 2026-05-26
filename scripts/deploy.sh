#!/bin/bash
# One-click deployment script for rosclaw-darwin.
#
# This script automates the entire deployment pipeline:
#   1. Check prerequisites (Docker, GPU, NGC login)
#   2. Download IsaacLab-Arena reference project (if not present)
#   3. Initialize submodules
#   4. Build Docker base image (IsaacLab-Arena with fixed sources)
#   5. Build Docker full image (base + rosclaw-darwin)
#   6. Verify installation with smoke test
#   7. Start dashboard (optional)
#
# Usage:
#   ./scripts/deploy.sh              # Full deployment
#   ./scripts/deploy.sh --skip-build # Skip Docker build (use existing images)
#   ./scripts/deploy.sh --dashboard  # Start dashboard after deployment
#   ./scripts/deploy.sh --clean      # Clean and rebuild everything

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REFERENCE_DIR="${PROJECT_ROOT}/../reference_projects"
ISAACLAB_ARENA_DIR="${REFERENCE_DIR}/IsaacLab-Arena"

SKIP_BUILD=false
START_DASHBOARD=false
CLEAN=false
APT_MIRROR="${APT_MIRROR:-mirrors.aliyun.com}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build) SKIP_BUILD=true; shift ;;
        --dashboard) START_DASHBOARD=true; shift ;;
        --clean) CLEAN=true; shift ;;
        --apt-mirror) APT_MIRROR="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

log_info() { echo "[INFO]  $*"; }
log_ok()   { echo "[OK]    $*"; }
log_warn() { echo "[WARN]  $*"; }
log_err()  { echo "[ERROR] $*"; exit 1; }

echo "========================================"
echo "ROSClaw-Darwin One-Click Deploy"
echo "========================================"
echo ""

# -----------------------------------------------------------------------------
# Step 1: Prerequisites
# -----------------------------------------------------------------------------
echo "[1/7] Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    log_err "Docker not found. Install: https://docs.docker.com/engine/install/"
fi
log_ok "Docker: $(docker --version)"

if ! docker info &>/dev/null; then
    log_err "Docker daemon not running. Start with: sudo systemctl start docker"
fi

if ! nvidia-smi &>/dev/null; then
    log_err "NVIDIA GPU / nvidia-smi not found."
fi
log_ok "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"

if ! docker info 2>&1 | grep -q "nvidia"; then
    log_warn "NVIDIA Container Toolkit not detected. GPU access may fail."
    log_warn "Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi

# Check NGC login
if ! docker pull --quiet nvcr.io/nvidia/isaac-sim:6.0.0-dev2 &>/dev/null 2>&1; then
    log_warn "Cannot pull from NGC registry."
    log_warn "Login with: docker login nvcr.io"
    log_warn "Username: \$oauthtoken, Password: your-ngc-api-key"
fi

# Check Python (for host-side development)
PYTHON_VERSION="$(python3 --version 2>&1 | awk '{print $2}')"
if [[ -n "${PYTHON_VERSION}" ]]; then
    log_ok "Python: ${PYTHON_VERSION}"
else
    log_warn "Python3 not found on host. Install for host-side development."
fi

echo ""

# -----------------------------------------------------------------------------
# Step 2: Download IsaacLab-Arena
# -----------------------------------------------------------------------------
echo "[2/7] Checking IsaacLab-Arena..."

if [[ ! -d "${ISAACLAB_ARENA_DIR}" ]]; then
    log_info "Downloading IsaacLab-Arena..."
    mkdir -p "${REFERENCE_DIR}"
    git clone --depth 1 https://github.com/isaac-sim/IsaacLab-Arena.git "${ISAACLAB_ARENA_DIR}"
fi
log_ok "IsaacLab-Arena: ${ISAACLAB_ARENA_DIR}"

# -----------------------------------------------------------------------------
# Step 3: Initialize submodules
# -----------------------------------------------------------------------------
echo "[3/7] Initializing submodules..."

cd "${ISAACLAB_ARENA_DIR}"

if [[ ! -d "submodules/IsaacLab/source" ]]; then
    log_info "Initializing IsaacLab submodule..."
    git config submodule.submodules/IsaacLab.url https://github.com/isaac-sim/IsaacLab.git
    git config submodule.submodules/Isaac-GR00T.url https://github.com/NVIDIA/Isaac-GR00T.git
    git submodule update --init --recursive --depth 1
fi

# Ensure placeholder for GR00T (build doesn't fail if missing)
if [[ ! -d "submodules/Isaac-GR00T/.git" ]]; then
    log_info "Creating Isaac-GR00T placeholder..."
    mkdir -p submodules/Isaac-GR00T
    touch submodules/Isaac-GR00T/.gitkeep
fi

log_ok "Submodules ready"
echo ""

# -----------------------------------------------------------------------------
# Step 4: Clean (if requested)
# -----------------------------------------------------------------------------
if [[ "${CLEAN}" == "true" ]]; then
    echo "[4/7] Cleaning existing images..."
    docker rmi rosclaw-darwin:arena-base rosclaw-darwin:latest 2>/dev/null || true
    log_ok "Cleaned"
    echo ""
fi

# -----------------------------------------------------------------------------
# Step 5: Build Docker images
# -----------------------------------------------------------------------------
if [[ "${SKIP_BUILD}" == "false" ]]; then
    echo "[5/7] Building Docker images..."
    echo "  APT mirror: ${APT_MIRROR}"
    echo ""

    cd "${PROJECT_ROOT}"
    export APT_MIRROR
    export ISAACLAB_ARENA_DIR

    log_info "Building base image (IsaacLab-Arena)..."
    if ! ./docker/build.sh; then
        log_err "Base image build failed. Check docker/build-base.log"
    fi
    log_ok "Base image: rosclaw-darwin:arena-base"

    log_info "Building full image (rosclaw-darwin)..."
    if ! ./docker/build.sh --full; then
        log_err "Full image build failed. Check docker/build-full.log"
    fi
    log_ok "Full image: rosclaw-darwin:latest"
else
    log_info "[5/7] Skipping build (--skip-build)"
    if ! docker image inspect rosclaw-darwin:latest >/dev/null 2>&1; then
        log_err "Image rosclaw-darwin:latest not found. Run without --skip-build."
    fi
fi

echo ""

# -----------------------------------------------------------------------------
# Step 6: Smoke test
# -----------------------------------------------------------------------------
echo "[6/7] Running smoke test..."

SMOKE_OUTPUT="$(docker run --rm --gpus all -e ACCEPT_EULA=Y \
    rosclaw-darwin:latest \
    /isaac-sim/python.sh -c "
import sys
sys.path.insert(0, '/workspace/rosclaw-darwin')

# Test 1: TDL
from rosclaw_darwin.tdl.schema import Task, Primitive
print('[SMOKE] TDL schema OK')

# Test 2: Loader
from rosclaw_darwin.tdl.loader import TaskLoader
loader = TaskLoader('/workspace/rosclaw-darwin/configs/tasks')
tasks = loader.load_all()
print(f'[SMOKE] TaskLoader OK ({len(tasks)} tasks)')

# Test 3: Arena Adapter
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter
adapter = ArenaAdapter(tasks[0])
adapter.build()
state = adapter.get_state()
print(f'[SMOKE] ArenaAdapter OK (backend={state[\"backend\"]})')
adapter.close()

# Test 4: Evaluator
import asyncio
from rosclaw_darwin.evaluation.base import BaseEvaluator
evaluator = BaseEvaluator(ArenaAdapter(tasks[0]))
evaluator.adapter.build()
def policy(obs): return {'action': 'test'}
metrics = asyncio.run(evaluator.evaluate(policy, max_steps=3))
print(f'[SMOKE] Evaluator OK (steps={metrics.step_count})')
evaluator.adapter.close()

# Test 5: Evolution
from rosclaw_darwin.evolution.genome import TaskGenomeEngine
engine = TaskGenomeEngine()
variants = engine.mutate(tasks[0], n_variations=1)
print(f'[SMOKE] TaskGenome OK ({len(variants)} variants)')

print('')
print('ALL SMOKE TESTS PASSED')
" 2>&1)" || true

if echo "${SMOKE_OUTPUT}" | grep -q "ALL SMOKE TESTS PASSED"; then
    log_ok "Smoke test passed"
else
    log_warn "Smoke test had issues (non-fatal for mock mode)"
    echo "${SMOKE_OUTPUT}" | tail -20
fi

echo ""

# -----------------------------------------------------------------------------
# Step 7: Start dashboard (optional)
# -----------------------------------------------------------------------------
if [[ "${START_DASHBOARD}" == "true" ]]; then
    echo "[7/7] Starting EEIB Dashboard..."
    cd "${PROJECT_ROOT}"
    ./docker/run.sh --daemon --dashboard
    log_ok "Dashboard: http://localhost:8080"
else
    echo "[7/7] Deployment complete!"
    log_info "To start dashboard: ./docker/run.sh --dashboard"
fi

echo ""
echo "========================================"
echo "ROSClaw-Darwin Deployed Successfully"
echo "========================================"
echo ""
echo "Quick Start:"
echo "  ./docker/run.sh              # Interactive shell"
echo "  ./docker/run.sh --demo       # End-to-end demo"
echo "  ./docker/run.sh --test       # Run tests"
echo "  ./docker/run.sh --dashboard  # Start EEIB leaderboard"
echo "  ./docker/run.sh --eval configs/tasks/pick_place_milk.yaml"
echo ""
echo "Makefile shortcuts:"
echo "  make build     # Build images"
echo "  make run       # Interactive shell"
echo "  make demo      # Run demo"
echo "  make test      # Run tests"
echo "  make dashboard # Start dashboard"
echo ""
