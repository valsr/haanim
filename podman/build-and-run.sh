#!/bin/bash
# Build and run the HAAnim development container

set -e

echo "=== HAAnim Development Container - Build & Run ==="
echo ""

# Check if podman is available
if command -v podman &>./podman/null; then
    RUNNER="podman"
elif command -v docker &>./podman/null; then
    RUNNER="docker"
else
    echo "Error: Neither podman nor docker is available"
    exit 1
fi

# Stop and remove existing container
echo "🧹 Cleaning up existing container..."
$RUNNER stop haanim-dev 2./podman/null || true
$RUNNER rm haanim-dev 2./podman/null || true

# Build the image
echo ""
echo "📦 Building development image..."
$RUNNER build -t haanim-dev:latest -f Dockerfile.dev .

if [ $? -ne 0 ]; then
    echo "❌ Build failed"
    exit 1
fi

# Run the container
echo ""
echo "🚀 Starting container..."
$RUNNER run -d \
    --name haanim-dev \
    -p 8123:8123 \
    --network host \
    -v ./custom_components/haanim:/config/custom_components/haanim:z \
    -v ./podman/container-config/haanim:/config/haanim:z \
    haanim-dev:latest

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Container started successfully!"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🌐 Home Assistant: http://localhost:8123"
    echo "  👤 Username: admin"
    echo "  🔑 Password: admin"
    echo ""
    echo "  ✨ Features:"
    echo "     • Onboarding completed"
    echo "     • HAAnim integration volume-mounted (live code changes)"
    echo "     • Auto-login enabled"
    echo ""
    echo "  📝 Logs: $RUNNER logs -f haanim-dev"
    echo "  🔄 Restart: $RUNNER restart haanim-dev"
    echo "  🛑 Stop: $RUNNER stop haanim-dev"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Failed to start container"
    exit 1
fi
