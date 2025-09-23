#!/bin/bash
# Stop development server

set -euo pipefail

APP_NAME="arcade-backend"
DEV_CONTAINER="$APP_NAME-dev"

echo "🛑 Stopping development server..."

if docker ps -q -f name="$DEV_CONTAINER" | grep -q .; then
    docker stop "$DEV_CONTAINER"
    docker rm "$DEV_CONTAINER"
    echo "✅ Development server stopped and container removed"
else
    echo "ℹ️  No running development container found"
fi
