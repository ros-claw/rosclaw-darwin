#!/bin/bash
# ROSClaw-Darwin container entrypoint.
#
# This script runs before any user command to set up the environment.

set -e

echo "========================================"
echo "ROSClaw-Darwin Container"
echo "========================================"

# Activate Isaac Sim environment
export PYTHONPATH="/isaac-sim:${PYTHONPATH}"
export PYTHONPATH="/isaac-sim/exts/isaacsim.simulation_app:${PYTHONPATH}"

# Alias Isaac Sim Python for convenience
alias python='/isaac-sim/python.sh'
alias pip='/isaac-sim/python.sh -m pip'

# Show environment info
echo "Isaac Sim: $(/isaac-sim/python.sh -c 'import omni; print(omni.__version__)' 2>/dev/null || echo 'not yet initialized')"
echo "ROSClaw-Darwin: $(/isaac-sim/python.sh -c 'import rosclaw_darwin; print(rosclaw_darwin.__version__)' 2>/dev/null || echo 'installed')"
echo ""

# Run the user command
exec "$@"
