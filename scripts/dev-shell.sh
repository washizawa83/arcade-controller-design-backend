#!/bin/bash
# Access development container shell

set -euo pipefail

APP_NAME="arcade-backend"
DEV_CONTAINER="$APP_NAME-dev"

echo "🔧 Accessing development container shell..."

if docker ps -q -f name="$DEV_CONTAINER" | grep -q .; then
    docker exec -it "$DEV_CONTAINER" bash
else
    echo "❌ Development container is not running"
    echo "Start it with: ./scripts/dev.sh"
    exit 1
fi
