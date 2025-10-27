#!/usr/bin/env bash
set -euo pipefail

# Push local image to AWS ECR and print IMAGE_URI to stdout
# Requires: aws cli v2, docker login permission to ECR

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
REGION=${AWS_REGION:-ap-northeast-1}
REPO_NAME=${ECR_REPO_NAME:-arcade-backend}
TAG=${TAG:-backend}

echo "[ECR] Resolving account ID"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [[ -z "$ACCOUNT_ID" || "$ACCOUNT_ID" == "None" ]]; then
  echo "Failed to resolve AWS account ID (check AWS_PROFILE/credentials)" >&2
  exit 1
fi

echo "[ECR] Ensure repository exists: $REPO_NAME"
set +e
aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" >/dev/null 2>&1
if [[ $? -ne 0 ]]; then
  aws ecr create-repository --repository-name "$REPO_NAME" --image-scanning-configuration scanOnPush=true --region "$REGION" >/dev/null
fi
set -e

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}:${TAG}"

echo "[ECR] Login Docker to ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "[ECR] Build/tag/push image"
docker buildx build --platform linux/amd64 -f "$ROOT_DIR/Dockerfile" -t "$REPO_NAME:$TAG" "$ROOT_DIR" --load
docker tag "$REPO_NAME:$TAG" "$ECR_URI"
docker push "$ECR_URI"

echo "$ECR_URI"


