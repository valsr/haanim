#!/bin/bash
# Build and run the HAAnim development container

set -e

echo "=== HAAnim Development Container - Run ==="
echo ""

# Run the container
echo ""
echo "🚀 Starting container..."
if podman run -d \
    --name haanim-dev \
    -p 8123:8123 \
    --network host \
    -v ./custom_components/haanim:/config/custom_components/haanim:z \
    -v ./src/haanim:/opt/haanim-src/haanim:z \
    -e PYTHONPATH=/opt/haanim-src \
    -v ./examples:/config/haanim/automations:z \
    haanim-dev:latest; then
    echo ""
    echo "✅ Container started successfully!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🌐 URL: http://localhost:8123"
    echo "  👤 Username: admin"
    echo "  🔑 Password: admin"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Failed to start container"
    exit 1
fi
