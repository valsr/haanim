#!/bin/bash
# Restart the Home Assistant development environment

set -e

echo "Restarting Home Assistant development environment..."
./stop.sh
./start.sh
