#!/bin/bash
# Build and run the HAAnim development container

set -e

if ! ./build-image.sh; then
    echo "❌ Build failed, aborting run"
    exit 1
fi

./start.sh
