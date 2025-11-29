#!/bin/bash
# Stop the Home Assistant development container

set -e

echo "🛑 Stopping container..."
podman stop haanim-dev &>/dev/null || true
echo "✅ Container stopped"
