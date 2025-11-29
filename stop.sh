#!/bin/bash
# Stop the Home Assistant development environment

set -e

echo "Stopping Home Assistant development environment..."
# Stop and remove existing container

echo "🧹 Cleaning up existing container..."
podman stop haanim-dev &>/dev/null || true
podman rm haanim-dev &>/dev/null || true
