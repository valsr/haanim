#!/bin/bash
# View logs from the Home Assistant development environment

echo "Showing Home Assistant logs (Ctrl+C to exit)..."
echo ""
podman logs -f haanim-dev
