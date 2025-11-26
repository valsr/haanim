#!/bin/bash
# Stop the Home Assistant development environment

set -e

echo "Stopping Home Assistant development environment..."
podman-compose down

echo "✓ Home Assistant stopped"
