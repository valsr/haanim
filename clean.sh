#!/bin/bash
# Remove the Home Assistant development container

set -e

echo "🧹 Removing container..."
podman rm haanim-dev &>/dev/null || true
echo "✅ Container removed"
