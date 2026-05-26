# ROSClaw-Darwin Makefile
# Convenient shortcuts for common operations.
#
# Usage:
#   make help       # Show all available targets
#   make build      # Build Docker images
#   make run        # Start interactive container
#   make demo       # Run end-to-end demo
#   make test       # Run test suite
#   make dashboard  # Start EEIB leaderboard
#   make deploy     # Full one-click deployment
#   make clean      # Remove all Docker artifacts

.PHONY: help build build-base build-full run demo test eval dashboard deploy clean status

# Configuration
IMAGE_TAG ?= rosclaw-darwin:latest
BASE_IMAGE_TAG ?= rosclaw-darwin:arena-base
CONTAINER_NAME ?= rosclaw_darwin
APT_MIRROR ?= mirrors.aliyun.com

help:
	@echo "ROSClaw-Darwin - Available Targets"
	@echo "====================================="
	@echo "  make build       Build base + full Docker images"
	@echo "  make build-base  Build IsaacLab-Arena base image only"
	@echo "  make build-full  Build rosclaw-darwin full image (needs base)"
	@echo "  make run         Start interactive container shell"
	@echo "  make demo        Run end-to-end demo inside container"
	@echo "  make test        Run pytest suite inside container"
	@echo "  make eval        Evaluate default task (pick_place_milk)"
	@echo "  make dashboard   Start EEIB dashboard on http://localhost:8080"
	@echo "  make deploy      Full one-click deployment"
	@echo "  make status      Show container and image status"
	@echo "  make clean       Remove containers, images, and volumes"
	@echo "  make logs        Follow container logs"
	@echo ""
	@echo "Environment variables:"
	@echo "  APT_MIRROR=$(APT_MIRROR)"
	@echo "  IMAGE_TAG=$(IMAGE_TAG)"
	@echo ""

# -----------------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------------

build: build-base build-full

build-base:
	@echo "Building base image..."
	APT_MIRROR=$(APT_MIRROR) ./docker/build.sh

build-full:
	@echo "Building full image..."
	APT_MIRROR=$(APT_MIRROR) ./docker/build.sh --full

build-rebuild:
	@echo "Force rebuilding all images..."
	APT_MIRROR=$(APT_MIRROR) ./docker/build.sh --rebuild --full

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------

run:
	@echo "Starting interactive shell..."
	./docker/run.sh

run-detached:
	@echo "Starting container in background..."
	./docker/run.sh --daemon

run-exec:
	@echo "Executing in running container..."
	docker exec -it $(CONTAINER_NAME) /bin/bash

# -----------------------------------------------------------------------------
# Demo & Test
# -----------------------------------------------------------------------------

demo:
	@echo "Running end-to-end demo..."
	./docker/run.sh --demo

test:
	@echo "Running test suite..."
	./docker/run.sh --test

# -----------------------------------------------------------------------------
# Evaluation
# -----------------------------------------------------------------------------

eval:
	@echo "Evaluating default task..."
	./docker/run.sh --eval configs/tasks/pick_place_milk.yaml

eval-fridge:
	@echo "Evaluating open_fridge task..."
	./docker/run.sh --eval configs/tasks/open_fridge.yaml

# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

dashboard:
	@echo "Starting EEIB Dashboard..."
	@echo "Open http://localhost:8080 in your browser"
	./docker/run.sh --dashboard

# -----------------------------------------------------------------------------
# Docker Compose
# -----------------------------------------------------------------------------

compose-up:
	@echo "Starting services with docker compose..."
	docker compose up -d

compose-up-dashboard:
	@echo "Starting dashboard service..."
	docker compose --profile dashboard up -d

compose-down:
	@echo "Stopping all services..."
	docker compose down

compose-logs:
	@echo "Following logs..."
	docker compose logs -f

# -----------------------------------------------------------------------------
# Deployment
# -----------------------------------------------------------------------------

deploy:
	@echo "Running one-click deployment..."
	./scripts/deploy.sh

deploy-dashboard:
	@echo "Deploying with dashboard..."
	./scripts/deploy.sh --dashboard

# -----------------------------------------------------------------------------
# Status & Cleanup
# -----------------------------------------------------------------------------

status:
	@echo "=== Docker Images ==="
	@docker images | grep rosclaw-darwin || echo "No rosclaw-darwin images found"
	@echo ""
	@echo "=== Running Containers ==="
	@docker ps --filter "name=rosclaw" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	@echo ""
	@echo "=== Volumes ==="
	@docker volume ls | grep darwin || echo "No darwin volumes found"
	@echo ""
	@echo "=== GPU Status ==="
	@nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "GPU info unavailable"

logs:
	@docker logs -f $(CONTAINER_NAME) 2>/dev/null || echo "Container $(CONTAINER_NAME) not running"

clean:
	@echo "Cleaning up Docker artifacts..."
	-docker stop $(CONTAINER_NAME) 2>/dev/null
	-docker rm $(CONTAINER_NAME) 2>/dev/null
	-docker rmi $(IMAGE_TAG) $(BASE_IMAGE_TAG) 2>/dev/null
	-docker compose down --volumes --remove-orphans 2>/dev/null
	@echo "Cleanup complete"

clean-all: clean
	@echo "Removing all build cache..."
	-docker builder prune -f
	@echo "All cleanup complete"
