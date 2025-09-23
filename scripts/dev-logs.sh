#!/bin/bash
# View development server logs

set -euo pipefail

APP_NAME="arcade-backend"
DEV_CONTAINER="$APP_NAME-dev"

echo "📊 Viewing development server logs..."
echo "Press Ctrl+C to stop following logs"
echo ""

if docker ps -q -f name="$DEV_CONTAINER" | grep -q .; then
    docker logs -f "$DEV_CONTAINER"
else
    echo "❌ Development container is not running"
    echo "Start it with: ./scripts/dev.sh"
    exit 1
fi
