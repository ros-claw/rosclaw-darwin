# ROSClaw-Darwin Deployment Guide

This guide covers all deployment options for ROSClaw-Darwin, from one-click deployment to manual Docker configuration.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (One-Click Deploy)](#quick-start-one-click-deploy)
- [Manual Deployment](#manual-deployment)
- [Docker Compose Deployment](#docker-compose-deployment)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | NVIDIA GPU with 8GB VRAM | RTX A6000 / A100 with 24GB+ VRAM |
| RAM | 32GB | 64GB+ |
| Disk | 100GB free | 200GB+ SSD |
| OS | Ubuntu 22.04 | Ubuntu 22.04 LTS |

### Software

```bash
# Docker
sudo apt update
sudo apt install -y docker.io docker-compose-plugin

# NVIDIA Container Toolkit
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker

# Verify
docker --version          # >= 24.0
nvidia-smi                # Driver >= 550, CUDA >= 12.0
docker info | grep nvidia # Should show nvidia runtime
```

### NGC Registry Login

Isaac Sim base image requires NVIDIA NGC login:

```bash
docker login nvcr.io
# Username: $oauthtoken
# Password: your-ngc-api-key
# Get key from: https://org.ngc.nvidia.com/setup/api-key
```

### GitHub Access (for ros-claw private repos)

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

---

## Quick Start (One-Click Deploy)

The fastest way to get started:

```bash
# Clone rosclaw-darwin
git clone https://github.com/ros-claw/rosclaw-darwin.git
cd rosclaw-darwin

# One-click deployment (downloads IsaacLab-Arena, builds images, runs smoke test)
./scripts/deploy.sh

# Or with dashboard
./scripts/deploy.sh --dashboard
```

This script automates the entire pipeline:
1. Checks prerequisites (Docker, GPU, NGC login)
2. Downloads IsaacLab-Arena reference project
3. Initializes submodules (IsaacLab, Isaac-GR00T)
4. Builds Docker base image (IsaacLab-Arena with fixed apt/pip sources)
5. Builds Docker full image (base + rosclaw-darwin)
6. Runs smoke test to verify installation
7. Optionally starts EEIB dashboard

**Estimated time:** 20-40 minutes (depends on network speed)

---

## Manual Deployment

### Step 1: Download IsaacLab-Arena

```bash
# The reference project is needed for Docker build
mkdir -p ../reference_projects
cd ../reference_projects
git clone --depth 1 https://github.com/isaac-sim/IsaacLab-Arena.git
cd IsaacLab-Arena

# Initialize submodules
git config submodule.submodules/IsaacLab.url https://github.com/isaac-sim/IsaacLab.git
git config submodule.submodules/Isaac-GR00T.url https://github.com/NVIDIA/Isaac-GR00T.git
git submodule update --init --recursive --depth 1

# Create GR00T placeholder (optional, build won't fail without it)
mkdir -p submodules/Isaac-GR00T
touch submodules/Isaac-GR00T/.gitkeep
```

### Step 2: Build Docker Images

```bash
cd /path/to/rosclaw-darwin

# Option A: Use Makefile (recommended)
make build

# Option B: Use build script directly
./docker/build.sh --full

# Option C: With custom apt mirror (for China mainland)
APT_MIRROR=mirrors.aliyun.com ./docker/build.sh --full

# Option D: Force rebuild (no cache)
make build-rebuild
```

**Build stages:**
- `Stage 1` (base): Downloads Isaac Sim base image, installs IsaacLab + Arena (~18GB)
- `Stage 2` (full): Adds rosclaw-darwin and dependencies (~500MB)

### Step 3: Verify Installation

```bash
# Run smoke test
make test

# Or manually
docker run --rm --gpus all -e ACCEPT_EULA=Y \
    rosclaw-darwin:latest \
    /isaac-sim/python.sh -m pytest /workspace/rosclaw-darwin/tests/ -v
```

### Step 4: Run Demo

```bash
make demo
```

---

## Docker Compose Deployment

For production or multi-service deployment:

```bash
# Start all services
docker compose up -d

# Start with dashboard only
docker compose --profile dashboard up -d

# Check status
docker compose ps

# View logs
docker compose logs -f

# Enter container
docker compose exec darwin bash

# Stop everything
docker compose down
```

### Compose Profiles

| Profile | Services | Use Case |
|---------|----------|----------|
| (default) | `darwin` | Development container with live reload |
| `dashboard` | `dashboard` | Standalone EEIB web server |
| `eval` | `eval` | One-shot evaluation runner |

### Environment Variables

```bash
# Custom data directories
export ROSCLAW_DATASETS=/mnt/data/datasets
export ROSCLAW_MODELS=/mnt/data/models
export ROSCLAW_EVAL=/mnt/data/eval

# GPU selection (multi-GPU systems)
export CUDA_VISIBLE_DEVICES=0,1

# Then start
docker compose up -d
```

---

## Configuration

### APT Mirror (for Chinese mainland users)

If you're in China, set the apt mirror for faster builds:

```bash
# Via environment variable
export APT_MIRROR=mirrors.aliyun.com

# Via Makefile
make build APT_MIRROR=mirrors.aliyun.com

# Via deploy script
APT_MIRROR=mirrors.aliyun.com ./scripts/deploy.sh
```

Available mirrors:
- `mirrors.aliyun.com` (阿里云)
- `mirrors.tuna.tsinghua.edu.cn` (清华)
- `mirrors.ustc.edu.cn` (中科大)

### PIP Mirror

The Dockerfile automatically configures Tsinghua pip mirror + NVIDIA NGC:

```
https://pypi.tuna.tsinghua.edu.cn/simple
https://pypi.ngc.nvidia.com
```

To override:

```bash
export PIP_INDEX=https://your-pip-mirror.com/simple
export PIP_EXTRA_INDEX=https://pypi.ngc.nvidia.com
./docker/build.sh
```

### Data Directories

Mount structure inside container:

```
/data/datasets    -> Task data, demonstrations
/data/models      -> Policy checkpoints
/data/eval        -> Evaluation results
/data/rosclaw     -> MCAP recordings, fallback events
/data/seekdb      -> SeekDB embedded data
```

Configure on host:

```bash
mkdir -p ~/datasets ~/models ~/eval
export ROSCLAW_DATASETS=~/datasets
export ROSCLAW_MODELS=~/models
export ROSCLAW_EVAL=~/eval
```

---

## Troubleshooting

### Build fails with "apt-get update" errors

**Cause:** Network issues with default Ubuntu apt sources.

**Fix:** Use China mainland mirror:
```bash
APT_MIRROR=mirrors.aliyun.com make build
```

### "Cannot pull Isaac Sim base image"

**Cause:** Not logged in to NVIDIA NGC registry.

**Fix:**
```bash
docker login nvcr.io
# Username: $oauthtoken
# Password: your-ngc-api-key
```

### "No NVIDIA GPU detected"

**Cause:** NVIDIA Container Toolkit not installed or Docker not configured.

**Fix:**
```bash
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### "Isaac Sim Kit startup takes 90+ seconds"

**Expected behavior.** Isaac Sim is a full Omniverse application, not a lightweight Python library. First startup is slow (~90s). Subsequent starts in a running container are instant.

**Optimization:** Keep container running:
```bash
docker compose up -d darwin
# Then exec into it
docker compose exec darwin bash
```

### "Permission denied on mounted volumes"

**Cause:** UID mismatch between host and container.

**Fix:**
```bash
# On host, set permissions
chmod -R 777 /path/to/mounted/directory

# Or use Docker user mapping
docker run --user $(id -u):$(id -g) ...
```

### Container exits immediately after start

**Cause:** Missing ACCEPT_EULA environment variable.

**Fix:**
```bash
docker run -e ACCEPT_EULA=Y ...
```

### "rosclaw-practice not found" warnings

**Expected.** rosclaw-darwin gracefully falls back to mock mode when ecosystem components are not available. Integration bridges are optional.

**To enable full integration:** Mount rosclaw repos:
```bash
docker run \
    -v /code/rosclaw/rosclaw-practice:/workspace/rosclaw-practice \
    -v /code/rosclaw/rosclaw-memory:/workspace/rosclaw-memory \
    ...
```

---

## Makefile Reference

| Command | Description |
|---------|-------------|
| `make help` | Show all available targets |
| `make build` | Build base + full images |
| `make build-base` | Build IsaacLab-Arena base only |
| `make build-full` | Build rosclaw-darwin layer |
| `make build-rebuild` | Force rebuild without cache |
| `make run` | Start interactive shell |
| `make run-detached` | Start container in background |
| `make run-exec` | Enter running container |
| `make demo` | Run end-to-end demo |
| `make test` | Run pytest suite |
| `make eval` | Evaluate default task |
| `make dashboard` | Start EEIB dashboard |
| `make deploy` | One-click deployment |
| `make status` | Show container/image status |
| `make clean` | Remove containers and images |
| `make clean-all` | Remove everything including cache |
