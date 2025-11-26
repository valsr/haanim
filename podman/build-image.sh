#!/bin/bash
# Build the HAAnim development container image

set -e

echo "=== Building HAAnim Development Container ==="
echo ""

# Check if podman is available
if command -v podman &>./podman/null; then
    BUILDER="podman"
elif command -v docker &>./podman/null; then
    BUILDER="docker"
else
    echo "Error: Neither podman nor docker is available"
    exit 1
fi

echo "Using: $BUILDER"
echo ""

# Build the image
echo "📦 Building image..."
$BUILDER build -t haanim-dev:latest -f Dockerfile.dev .

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Build complete!"
    echo ""
    echo "Image: haanim-dev:latest"
    echo ""
    echo "To run:"
    echo "  ./podman/build-and-run.sh"
    echo ""
    echo "Or manually:"
    echo "  $BUILDER run -d --name haanim-dev -p 8123:8123 --network host haanim-dev:latest"
    echo ""
else
    echo ""
    echo "❌ Build failed"
    exit 1
fi
