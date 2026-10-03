#!/bin/bash
# Build and run the HAAnim development container

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== HAAnim Development Container - Build & Run ==="
echo ""

# Check if podman is available
if ! command -v podman &>/dev/null; then
    echo "❌ Error: podman is not installed"
    echo "Please install podman first: https://podman.io/getting-started/installation"
    exit 1
fi

# Stop and clean existing container
"$ROOT_DIR/stop.sh" 2>/dev/null || true
"$ROOT_DIR/clean.sh" 2>/dev/null || true

# Build the image
echo ""
echo "📦 Building development image..."
if ! podman build -t haanim-dev:latest -f "$ROOT_DIR/Dockerfile" "$ROOT_DIR"; then
    echo "❌ Build failed"
    exit 1
fi

# Run the container
echo ""
echo "🚀 Starting container..."
if podman run -d \
    --name haanim-dev \
    -p 8123:8123 \
    -p 5678:5678 \
    --network host \
    -v "$ROOT_DIR/custom_components/haanim:/config/custom_components/haanim:z" \
    -v "$ROOT_DIR/src/haanim:/opt/haanim-src/haanim:z" \
    -e PYTHONPATH=/opt/haanim-src \
    -v "$ROOT_DIR/podman/container-config/haanim:/config/haanim:z" \
    haanim-dev:latest; then
    echo ""
    echo "✅ Container started successfully!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🌐 URL: http://localhost:8123"
    echo "  🐛 Debug: localhost:5678"
    echo "  👤 Username: admin"
    echo "  🔑 Password: admin"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Failed to start container"
    exit 1
fi
