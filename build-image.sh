#!/bin/bash
# Build and run the HAAnim development container

set -e

echo "=== HAAnim Development Container - Build ==="
echo ""

# Check if podman is available
if ! command -v podman &>/dev/null; then
    echo "❌ Error: podman is not installed"
    echo "Please install podman first: https://podman.io/getting-started/installation"
    exit 1
fi

# Build the image
echo "📦 Building image..."
if podman build -t haanim-dev:latest -f Dockerfile .; then
    echo ""
    echo "✅ Build complete!"
    echo ""
    echo "Image: haanim-dev:latest"
else
    echo ""
    echo "❌ Build failed"
    exit 1
fi
