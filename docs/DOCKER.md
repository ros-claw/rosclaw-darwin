# ROSClaw-Darwin Docker Usage

This document covers Docker-specific usage patterns for rosclaw-darwin.

## Architecture

```
Host Machine
  |
  |-- Docker Daemon
  |     |
  |     |-- rosclaw-darwin:latest  (Full Image)
  |     |    |
  |     |    |-- Isaac Sim 6.0.0   (Base Layer, 18.7GB)
  |     |    |-- IsaacLab 3.0     (Robot Learning Framework)
  |     |    |-- IsaacLab-Arena   (Composable Environments)
  |     |    |-- rosclaw-darwin   (This Project)
  |     |    |-- Dashboard        (FastAPI Web UI)
  |     |
  |     |-- Volumes:
  |     |    |-- darwin-data      (MCAP, fallback events)
  |     |    |-- darwin-seekdb    (Memory database)
  |     |
  |     |-- Ports:
  |          |-- 8080 -> EEIB Dashboard
  |          |-- 5678 -> Debugpy (VSCode remote debug)
```

## Image Layers

### Layer 1: Base (`rosclaw-darwin:arena-base`)

Contains everything needed to run Isaac Sim + IsaacLab + Arena.

```
FROM nvcr.io/nvidia/isaac-sim:6.0.0-dev2
+ apt packages (git, cmake, ffmpeg, pip)
+ IsaacLab (from submodule)
+ IsaacLab-Arena (from source)
+ pip dependencies
```

**Size:** ~22GB
**Build time:** 20-30 minutes
**Rebuilt when:** Isaac Sim version changes, IsaacLab submodule updates

### Layer 2: Full (`rosclaw-darwin:latest`)

Adds rosclaw-darwin on top of the base.

```
FROM rosclaw-darwin:arena-base
+ rosclaw-darwin source code
+ fastapi/uvicorn (dashboard deps)
+ data directories
+ entrypoint configuration
```

**Size:** ~500MB on top of base
**Build time:** 1-2 minutes
**Rebuilt when:** rosclaw-darwin code changes

## Common Workflows

### Development Workflow (Recommended)

Keep container running, edit code on host, changes reflect immediately:

```bash
# Terminal 1: Start container in background
make run-detached

# Terminal 2: Edit code on host
vim rosclaw_darwin/evolution/runner.py

# Terminal 3: Execute in running container
make run-exec
# Inside container:
/isaac-sim/python.sh -m pytest /workspace/rosclaw-darwin/tests/test_evolution.py -v
```

### Evaluation Workflow

Run a single evaluation task:

```bash
# Evaluate a specific task YAML
make eval

# Or with custom task
./docker/run.sh --eval /path/to/your/task.yaml

# Evaluate in background, save results
./docker/run.sh --daemon --eval configs/tasks/pick_place_milk.yaml
```

### Dashboard Workflow

Run the EEIB leaderboard web server:

```bash
# Start dashboard
make dashboard
# Open http://localhost:8080

# Submit a result
curl -X POST http://localhost:8080/api/submit \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "my_agent",
    "model": "pi0",
    "evolution_score": 0.85,
    "sdr": 0.72,
    "mie": 0.91,
    "ssi": 0.0,
    "tasks_evaluated": 10
  }'

# View leaderboard
curl http://localhost:8080/api/leaderboard
```

### Batch Evaluation Workflow

Evaluate multiple agents across multiple tasks:

```bash
# Create a batch script
cat > /tmp/batch_eval.py << 'EOF'
import asyncio, sys
sys.path.insert(0, '/workspace/rosclaw-darwin')
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.evolution.runner import EvolutionRunner
from rosclaw_darwin.environment.arena_adapter import ArenaAdapter

loader = TaskLoader('/workspace/rosclaw-darwin/configs/tasks')
tasks = loader.load_all()

def adapter_factory(task):
    a = ArenaAdapter(task)
    a.build()
    return a

runner = EvolutionRunner(adapter_factory)

for task in tasks:
    report = asyncio.run(runner.evaluate_evolution(task, lambda obs: {'action': 'test'}))
    print(f"{task.id}: score={report['evolution_score']:.3f}")
EOF

# Run in container
docker exec rosclaw_darwin /isaac-sim/python.sh /tmp/batch_eval.py
```

## Container Environment

### Inside the Container

| Path | Description |
|------|-------------|
| `/isaac-sim/` | Isaac Sim installation |
| `/isaac-sim/python.sh` | Isaac Sim Python interpreter |
| `/workspace/rosclaw-darwin/` | rosclaw-darwin source (mounted) |
| `/workspace/submodules/IsaacLab/` | IsaacLab source |
| `/data/datasets/` | Datasets (mounted from host) |
| `/data/models/` | Model checkpoints (mounted) |
| `/data/eval/` | Evaluation outputs (mounted) |
| `/data/rosclaw/` | MCAP recordings |
| `/data/seekdb/` | SeekDB data |

### Python Aliases

```bash
# Inside container, these aliases are available:
python   # -> /isaac-sim/python.sh
pip      # -> /isaac-sim/python.sh -m pip
pytest   # -> /isaac-sim/python.sh -m pytest
debugpy  # -> python -m debugpy --listen localhost:5678 --wait-for-client
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ACCEPT_EULA` | `Y` | Accept Isaac Sim EULA |
| `ROSCLAW_PRACTICE_MCAP_DIR` | `/data/rosclaw/mcap` | MCAP recording directory |
| `ROSCLAW_PRACTICE_FALLBACK_DIR` | `/data/rosclaw/fallback` | Fallback event storage |
| `SEEKDB_MODE` | `embedded` | SeekDB mode (embedded/server) |
| `SEEKDB_PATH` | `/data/seekdb/darwin` | SeekDB data path |
| `CUDA_VISIBLE_DEVICES` | `0` | GPU device selection |

## Advanced Usage

### Multi-GPU Setup

```bash
# Use GPU 0 and 1
docker run --gpus '"device=0,1"' -e CUDA_VISIBLE_DEVICES=0,1 \
    rosclaw-darwin:latest ...

# Or with docker-compose
export CUDA_VISIBLE_DEVICES=0,1
docker compose up -d
```

### Custom Task Definitions

Mount your own task configs:

```bash
docker run \
    -v $(pwd)/my_tasks:/data/tasks \
    rosclaw-darwin:latest \
    /isaac-sim/python.sh -c "
from rosclaw_darwin.tdl.loader import TaskLoader
loader = TaskLoader('/data/tasks')
# ... evaluate
"
```

### Debugging with VSCode

The container exposes debugpy on port 5678:

```json
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Attach to rosclaw-darwin",
            "type": "debugpy",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5678
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}",
                    "remoteRoot": "/workspace/rosclaw-darwin"
                }
            ]
        }
    ]
}
```

Start debug session:
```bash
# In container
debugpy /workspace/rosclaw-darwin/examples/demo.py

# Or via docker exec
docker exec rosclaw_darwin debugpy /workspace/rosclaw-darwin/examples/demo.py
```

### Persistent Data Storage

Docker Compose automatically creates named volumes:

```bash
# View volumes
docker volume ls | grep darwin

# Backup data
docker run --rm -v darwin-data:/data -v $(pwd)/backup:/backup \
    alpine tar czf /backup/rosclaw-data.tar.gz -C /data .

# Restore data
docker run --rm -v darwin-data:/data -v $(pwd)/backup:/backup \
    alpine tar xzf /backup/rosclaw-data.tar.gz -C /data
```

### Resource Limits

Limit GPU memory or CPU:

```bash
docker run \
    --gpus all \
    --memory=32g \
    --cpus=8 \
    rosclaw-darwin:latest ...
```

---

## Useful Docker Commands

```bash
# List rosclaw-darwin images
docker images | grep rosclaw-darwin

# Check container status
docker ps --filter "name=rosclaw"

# Inspect container
docker inspect rosclaw_darwin

# View container logs
docker logs rosclaw_darwin

# Follow logs in real-time
docker logs -f rosclaw_darwin

# Copy files in/out
docker cp rosclaw_darwin:/data/eval/results.json ./results.json
docker cp ./my_task.yaml rosclaw_darwin:/data/tasks/

# Execute single command
docker exec rosclaw_darwin /isaac-sim/python.sh -c "print('hello')"

# Restart container
docker restart rosclaw_darwin

# Remove everything
docker stop rosclaw_darwin
docker rm rosclaw_darwin
docker rmi rosclaw-darwin:latest
```
