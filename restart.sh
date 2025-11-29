#!/bin/bash
# Restart the Home Assistant development environment

set -e

echo "🔄 Restarting Home Assistant development environment..."
./stop.sh

# Check if container exists and start it, otherwise start.sh will create a new one
if podman ps -a --format '{{.Names}}' | grep -q '^haanim-dev$'; then
    echo "▶️  Container exists, starting it..."
    podman start haanim-dev
    exit 0
fi

echo "🆕 Container does not exist, creating new one..."
./start.sh
