#!/bin/bash
# Development server startup script using Docker

set -euo pipefail

echo "🐳 Starting development server with Docker..."

# 設定
APP_NAME="arcade-backend"
DEV_IMAGE="$APP_NAME:dev"
DEV_CONTAINER="$APP_NAME-dev"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 既存のコンテナを停止・削除
echo "🧹 Cleaning up existing containers..."
docker stop "$DEV_CONTAINER" 2>/dev/null || true
docker rm "$DEV_CONTAINER" 2>/dev/null || true

# 開発用Dockerイメージをビルド
echo "🔨 Building development Docker image..."
docker build --platform=linux/amd64 -f "$ROOT_DIR/Dockerfile" -t "$DEV_IMAGE" "$ROOT_DIR"

# 開発用コンテナを起動
echo "🚀 Starting development container..."
docker run --platform=linux/amd64 -d \
  --name "$DEV_CONTAINER" \
  -p 8080:8080 \
  -v "$ROOT_DIR:/app" \
  -w /app \
  -e PYTHONPATH=/opt/site-packages \
  -e USE_XVFB=1 \
  "$DEV_IMAGE" \
  python3 -m uvicorn app.src.main:app --reload --host 0.0.0.0 --port 8080

echo "✅ Development server started!"
echo "📍 API URL: http://localhost:8080"
echo "📋 Health check: curl http://localhost:8080/health"
echo "📋 API docs: http://localhost:8080/docs"
echo ""
echo "🛑 To stop: docker stop $DEV_CONTAINER"
echo "📊 To view logs: docker logs -f $DEV_CONTAINER"
echo "🔧 To access shell: docker exec -it $DEV_CONTAINER bash"
