#!/usr/bin/env bash
set -euo pipefail

# Deploy current backend Docker image to AWS Lightsail Container Service
# Prereqs: aws cli v2 logged in with permissions; docker buildx; region set

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SERVICE_NAME=${SERVICE_NAME:-arcade-backend}
REGION=${AWS_REGION:-ap-northeast-1}
LABEL=${LABEL:-backend}
POWER=${POWER:-medium} # medium ~= 1 vCPU / 2 GB
SCALE=${SCALE:-1}

# Ensure lightsailctl v1.0.7+ available locally (avoid old global installs)
BIN_DIR="$ROOT_DIR/.bin"
mkdir -p "$BIN_DIR"
if ! "$BIN_DIR/lightsailctl" --version >/dev/null 2>&1; then
  ARCH=$(uname -m)
  URL="https://s3.us-west-2.amazonaws.com/lightsailctl/latest/darwin-arm64/lightsailctl"
  if [ "$ARCH" != "arm64" ] && [ "$ARCH" != "aarch64" ]; then
    URL="https://s3.us-west-2.amazonaws.com/lightsailctl/latest/darwin-amd64/lightsailctl"
  fi
  echo "[0/5] Fetch lightsailctl from $URL"
  curl -fsSL "$URL" -o "$BIN_DIR/lightsailctl"
  chmod +x "$BIN_DIR/lightsailctl"
fi
export PATH="$BIN_DIR:$PATH"
echo "lightsailctl: $($BIN_DIR/lightsailctl --version || echo not-found)"

# Resolve image reference from env (README flow)
if [[ -z "${IMAGE_URI:-}" && -n "${IMAGE_ALIAS:-}" ]]; then
  IMAGE_URI="$IMAGE_ALIAS"
fi

if [[ -z "${IMAGE_URI:-}" ]]; then
  echo "ERROR: IMAGE_URI (or IMAGE_ALIAS) is required." >&2
  echo "Run the following (as in README):" >&2
  echo "  aws lightsail push-container-image --region $REGION --service-name $SERVICE_NAME --label $LABEL --image ${SERVICE_NAME}:${LABEL}" >&2
  echo "  export IMAGE_ALIAS=\":${SERVICE_NAME}.${LABEL}.<N>\"  # push の出力に表示されたエイリアス" >&2
  echo "  IMAGE_URI=\"$IMAGE_ALIAS\" SERVICE_NAME=$SERVICE_NAME POWER=$POWER SCALE=$SCALE bash scripts/deploy-lightsail.sh" >&2
  exit 2
fi

echo "[1/5] Skip build (using provided IMAGE_URI/ALIAS)"

echo "[2/5] Ensure container service exists"
set +e
aws lightsail create-container-service \
  --service-name "$SERVICE_NAME" \
  --power "$POWER" \
  --scale "$SCALE" \
  --region "$REGION" >/dev/null 2>&1
set -e

echo "[3/5] Resolve image for deployment"
IMAGE_REF="$IMAGE_URI"
echo "  -> Image reference: $IMAGE_REF"

TMP_DIR=$(mktemp -d)
CONTAINERS_JSON="$TMP_DIR/containers.json"
ENDPOINT_JSON="$TMP_DIR/endpoint.json"

cat > "$CONTAINERS_JSON" <<JSON
{
  "${SERVICE_NAME}": {
    "image": "${IMAGE_REF}",
    "ports": { "8080": "HTTP" },
    "environment": {
      "PORT": "8080",
      "USE_XVFB": "1",
      "PYTHONPATH": "/opt/site-packages",
      "JAVA_TOOL_OPTIONS": "-Xms256m -Xmx1024m"
    }
  }
}
JSON

cat > "$ENDPOINT_JSON" <<JSON
{
  "containerName": "${SERVICE_NAME}",
  "containerPort": 8080,
  "healthCheck": {
    "path": "/api/v1/health/",
    "intervalSeconds": 15,
    "timeoutSeconds": 5,
    "healthyThreshold": 2,
    "unhealthyThreshold": 5
  }
}
JSON

echo "[4/5] Create deployment"
aws lightsail create-container-service-deployment \
  --service-name "$SERVICE_NAME" \
  --containers file://"$CONTAINERS_JSON" \
  --public-endpoint file://"$ENDPOINT_JSON" \
  --region "$REGION"

echo "[5/5] Describe service endpoint"
aws lightsail get-container-services \
  --service-name "$SERVICE_NAME" \
  --region "$REGION" \
  --query 'containerServices[0].url'

echo "Done. Hit: http(s)://<printed-url>/api/v1/health/"


