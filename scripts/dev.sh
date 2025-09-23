#!/bin/bash
# Development server startup script using Docker

set -euo pipefail

echo "🐳 Starting development server with Docker..."

# 設定
APP_NAME="arcade-backend"
DEV_IMAGE="$APP_NAME:dev"
DEV_CONTAINER="$APP_NAME-dev"

# 既存のコンテナを停止・削除
echo "🧹 Cleaning up existing containers..."
docker stop "$DEV_CONTAINER" 2>/dev/null || true
docker rm "$DEV_CONTAINER" 2>/dev/null || true

# 開発用Dockerイメージをビルド
echo "🔨 Building development Docker image..."
docker build -t "$DEV_IMAGE" .

# 開発用コンテナを起動
echo "🚀 Starting development container..."
docker run -d \
  --name "$DEV_CONTAINER" \
  -p 8080:8080 \
  -v "$(pwd):/app" \
  -w /app \
  "$DEV_IMAGE" \
  /opt/venv/bin/uvicorn app.src.main:app --reload --host 0.0.0.0 --port 8080

echo "✅ Development server started!"
echo "📍 API URL: http://localhost:8080"
echo "📋 Health check: curl http://localhost:8080/health"
echo "📋 API docs: http://localhost:8080/docs"
echo ""
echo "🛑 To stop: docker stop $DEV_CONTAINER"
echo "📊 To view logs: docker logs -f $DEV_CONTAINER"
echo "🔧 To access shell: docker exec -it $DEV_CONTAINER bash"
