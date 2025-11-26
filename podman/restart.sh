#!/bin/bash
# Restart the Home Assistant development environment

set -e

echo "Restarting Home Assistant development environment..."
podman-compose restart

echo ""
echo "✓ Home Assistant restarted"
echo "  Web interface: http://localhost:8123"
