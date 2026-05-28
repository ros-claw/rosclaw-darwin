#!/bin/bash
# Run rosclaw-darwin Docker container.
#
# Usage:
#   ./docker/run.sh                    # Start interactive bash shell
#   ./docker/run.sh --demo             # Run the end-to-end demo
#   ./docker/run.sh --test             # Run pytest suite
#   ./docker/run.sh --eval TASK_YAML   # Evaluate a specific task
#   ./docker/run.sh --dashboard        # Start EEIB dashboard
#   ./docker/run.sh --daemon           # Run as background daemon

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE_TAG="${ROSCLAW_DARWIN_IMAGE:-rosclaw-darwin:latest}"
CONTAINER_NAME="${ROSCLAW_DARWIN_CONTAINER:-rosclaw_darwin}"
GPUS="${ROSCLAW_DARWIN_GPUS:-all}"

# Default mount directories
DATASETS_DIR="${ROSCLAW_DATASETS:-$HOME/datasets}"
MODELS_DIR="${ROSCLAW_MODELS:-$HOME/models}"
EVAL_DIR="${ROSCLAW_EVAL:-$HOME/eval}"

# Parse arguments
MODE="interactive"
TASK_FILE=""
DAEMON=false
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --demo)
            MODE="demo"
            shift
            ;;
        --test)
            MODE="test"
            shift
            ;;
        --eval)
            MODE="eval"
            TASK_FILE="$2"
            shift 2
            ;;
        --dashboard)
            MODE="dashboard"
            shift
            ;;
        --daemon)
            DAEMON=true
            shift
            ;;
        --name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --image)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --gpus)
            GPUS="$2"
            shift 2
            ;;
        --)
            shift
            EXTRA_ARGS+=("$@")
            break
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Usage: $0 [--demo|--test|--eval TASK|--dashboard|--daemon] [options]"
            exit 1
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Check if image exists
if ! docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
    echo "ERROR: Image '${IMAGE_TAG}' not found."
    echo "Build it first: ./docker/build.sh --full"
    exit 1
fi

# Build docker run arguments
DOCKER_ARGS=(
    --name "${CONTAINER_NAME}"
    --gpus "${GPUS}"
    -e ACCEPT_EULA=Y
    -e PYTHONUNBUFFERED=1
    -e ROSCLAW_PRACTICE_MCAP_DIR=/data/rosclaw/mcap
    -e ROSCLAW_PRACTICE_FALLBACK_DIR=/data/rosclaw/fallback
    -e SEEKDB_MODE=embedded
    -e SEEKDB_PATH=/data/seekdb/darwin
)

# Mount directories
DOCKER_ARGS+=(
    -v "${PROJECT_ROOT}:/workspace/rosclaw-darwin"
    -v "${DATASETS_DIR}:/data/datasets"
    -v "${MODELS_DIR}:/data/models"
    -v "${EVAL_DIR}:/data/eval"
)

# Mount IsaacLab-Arena subdirectories (source of truth for development iteration)
# The Dockerfile copies individual subdirectories, so we mount them individually
# to ensure editable installs in the container point to live code.
ISAACLAB_ARENA_DIR="${ISAACLAB_ARENA_DIR:-/code/rosclaw/rosclaw_darwin/reference_projects/IsaacLab-Arena}"
if [[ -d "${ISAACLAB_ARENA_DIR}" ]]; then
    # Core packages
    for pkg in isaaclab_arena isaaclab_arena_g1 isaaclab_arena_gr00t isaaclab_arena_openpi isaaclab_arena_environments; do
        if [[ -d "${ISAACLAB_ARENA_DIR}/${pkg}" ]]; then
            DOCKER_ARGS+=("-v" "${ISAACLAB_ARENA_DIR}/${pkg}:/workspace/${pkg}")
        fi
    done
    # Submodules (IsaacLab, Isaac-GR00T, etc.)
    if [[ -d "${ISAACLAB_ARENA_DIR}/submodules" ]]; then
        for submod in "${ISAACLAB_ARENA_DIR}/submodules"/*; do
            if [[ -d "${submod}" ]]; then
                name="$(basename "${submod}")"
                DOCKER_ARGS+=("-v" "${submod}:/workspace/submodules/${name}")
            fi
        done
    fi
fi

# Mount Omniverse assets if available
if [[ -d "/data/omniverse" ]]; then
    DOCKER_ARGS+=("-v" "/data/omniverse:/data/omniverse")
fi

# Mount rosclaw ecosystem if available
for repo in rosclaw-practice rosclaw-memory rosclaw-know rosclaw-how; do
    REPO_PATH="/code/rosclaw/${repo}"
    if [[ -d "${REPO_PATH}" ]]; then
        DOCKER_ARGS+=("-v" "${REPO_PATH}:/workspace/${repo}")
    fi
done

# Port mapping for dashboard
if [[ "${MODE}" == "dashboard" ]]; then
    DOCKER_ARGS+=(-p 8080:8080)
fi

# Daemon mode
if [[ "${DAEMON}" == "true" ]]; then
    DOCKER_ARGS+=(-d)
# Non-interactive modes (eval, test) may run without a TTY (CI/pipes).
# Only allocate a pseudo-TTY when stdin is actually a terminal.
elif [[ "${MODE}" == "eval" || "${MODE}" == "test" ]]; then
    if [[ -t 0 ]]; then
        DOCKER_ARGS+=(-it)
    else
        DOCKER_ARGS+=(-i)
    fi
else
    DOCKER_ARGS+=(-it)
fi

# Remove container on stop
DOCKER_ARGS+=(--rm)

echo "========================================"
echo "ROSClaw-Darwin Container"
echo "========================================"
echo "Image:    ${IMAGE_TAG}"
echo "Name:     ${CONTAINER_NAME}"
echo "GPUs:     ${GPUS}"
echo "Mode:     ${MODE}"
echo "========================================"

# Stop existing container if running
if docker ps -q --filter "name=^/${CONTAINER_NAME}$" >/dev/null 2>&1; then
    echo "Stopping existing container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
fi

# Run container based on mode
case "${MODE}" in
    interactive)
        echo "Starting interactive shell..."
        docker run "${DOCKER_ARGS[@]}" "${IMAGE_TAG}" /bin/bash
        ;;

    demo)
        echo "Running end-to-end demo..."
        docker run "${DOCKER_ARGS[@]}" "${IMAGE_TAG}" \
            /isaac-sim/python.sh /workspace/rosclaw-darwin/examples/demo.py
        ;;

    test)
        echo "Running test suite..."
        docker run "${DOCKER_ARGS[@]}" "${IMAGE_TAG}" \
            /isaac-sim/python.sh -m pytest /workspace/rosclaw-darwin/tests/ -v
        ;;

    eval)
        if [[ -z "${TASK_FILE}" ]]; then
            echo "ERROR: --eval requires a task YAML file path"
            exit 1
        fi
        TASK_BASENAME="$(basename "${TASK_FILE}")"
        echo "Evaluating task: ${TASK_BASENAME}"
        docker run "${DOCKER_ARGS[@]}" \
            -e ROSCLAW_ARENA_MODE=docker \
            -v "$(dirname "${TASK_FILE}"):/data/task" \
            "${IMAGE_TAG}" \
            /isaac-sim/python.sh -c "
import sys, torch
sys.path.insert(0, '/workspace/rosclaw-darwin')
sys.path.insert(0, '/workspace/rosclaw-darwin/stubs')
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter

loader = TaskLoader()
task = loader.load('/data/task/${TASK_BASENAME}')
adapter = ArenaAdapter(task, headless=True)
adapter.build()

def policy(obs):
    device = getattr(adapter._env, 'device', None) or getattr(adapter._env.unwrapped, 'device', torch.device('cuda:0'))
    return torch.zeros(adapter._env.action_space.shape, device=device)

obs = adapter.reset()
for step in range(100):
    action = policy(obs)
    obs, reward, done, info = adapter.step(action)
    if done:
        break

print(f'Isaac Sim evaluation WORKS! Steps: {step + 1}')
adapter.close()
"
        ;;

    dashboard)
        echo "Starting EEIB Dashboard on http://localhost:8080 ..."
        docker run "${DOCKER_ARGS[@]}" \
            -p 8080:8080 \
            "${IMAGE_TAG}" \
            /isaac-sim/python.sh -m rosclaw_darwin.dashboard.app
        ;;

    *)
        echo "ERROR: Unknown mode: ${MODE}"
        exit 1
        ;;
esac
