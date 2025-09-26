#!/bin/bash

# AWS ECS Fargate デプロイスクリプト
# 使用方法: ./deploy.sh [タグ名]

set -euo pipefail

# 設定
AWS_PROFILE="${AWS_PROFILE:-new-acct}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
APP_NAME="arcade-backend"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# タグ名を設定（引数があれば使用、なければタイムスタンプ）
if [ $# -eq 0 ]; then
    TAG="deploy-$(date +%s)"
else
    TAG="$1"
fi

echo "🚀 デプロイ開始: $TAG"

# AWS認証情報確認
echo "📋 AWS認証情報確認..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$AWS_REGION" --profile "$AWS_PROFILE")
echo "Account ID: $ACCOUNT_ID"

# ECRリポジトリURI
REPO_URI="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$APP_NAME"
echo "ECR Repository: $REPO_URI"

# Dockerビルドとプッシュ
echo "🔨 Dockerイメージビルド中..."
aws ecr get-login-password --region "$AWS_REGION" --profile "$AWS_PROFILE" | \
    docker login --username AWS --password-stdin "$REPO_URI" >/dev/null

docker buildx build --platform linux/amd64 -f "$ROOT_DIR/Dockerfile" -t "$REPO_URI:$TAG" "$ROOT_DIR" --push
echo "✅ イメージプッシュ完了: $REPO_URI:$TAG"

# タスク定義更新
echo "📝 タスク定義更新中..."
TD_ARN=$(aws ecs describe-services --cluster "$APP_NAME" --services "$APP_NAME-svc" --region "$AWS_REGION" --profile "$AWS_PROFILE" --query 'services[0].taskDefinition' --output text)

aws ecs describe-task-definition --task-definition "$TD_ARN" --region "$AWS_REGION" --profile "$AWS_PROFILE" --query 'taskDefinition' > /tmp/td-current.json

# 新しいタスク定義を作成
export IMAGE_REF="$REPO_URI:$TAG"
python3 -c "
import json, os
with open('/tmp/td-current.json') as f:
    td = json.load(f)

# 不要なフィールドを削除
for k in ['revision','status','taskDefinitionArn','requiresAttributes','compatibilities','registeredAt','registeredBy']:
    td.pop(k, None)

# AMD64ランタイムを強制
td['runtimePlatform'] = {'cpuArchitecture':'X86_64','operatingSystemFamily':'LINUX'}

# FargateのタスクレベルCPU/メモリ（1 vCPU / 2 GB）
td['cpu'] = '1024'
td['memory'] = '2048'

# イメージを更新
img = os.environ['IMAGE_REF']
if td['containerDefinitions']:
    # 1つ目のコンテナ定義を更新（本サービス想定）
    c = td['containerDefinitions'][0]
    c['image'] = img
    # 既存のentryPoint/commandをクリアしてDockerfileのCMD/ENTRYPOINTを使用
    c.pop('entryPoint', None)
    c.pop('command', None)
    # JAVAヒープ上限を設定してOOMを緩和
    env = {e['name']: e['value'] for e in c.get('environment', [])}
    env['JAVA_TOOL_OPTIONS'] = env.get('JAVA_TOOL_OPTIONS', '-Xms256m -Xmx1024m')
    c['environment'] = [{'name': k, 'value': v} for k, v in env.items()]
    # コンテナレベルのメモリ上書きをクリア（タスクレベル設定に委譲）
    c.pop('memoryReservation', None)
    c.pop('memory', None)

with open('/tmp/td-new.json', 'w') as f:
    json.dump(td, f)

print('New task definition created')
"

# 新しいタスク定義を登録
NEW_TD_ARN=$(aws ecs register-task-definition --cli-input-json file:///tmp/td-new.json --region "$AWS_REGION" --profile "$AWS_PROFILE" --query 'taskDefinition.taskDefinitionArn' --output text)
echo "✅ 新しいタスク定義登録完了: $NEW_TD_ARN"

# サービス更新
echo "🔄 サービス更新中..."
aws ecs update-service --cluster "$APP_NAME" --service "$APP_NAME-svc" \
  --task-definition "$NEW_TD_ARN" \
  --health-check-grace-period-seconds 300 \
  --force-new-deployment --region "$AWS_REGION" --profile "$AWS_PROFILE" >/dev/null
echo "✅ サービス更新完了"

# デプロイ完了待機
echo "⏳ デプロイ完了待機中..."
for i in {1..36}; do
    TASK_ARN=$(aws ecs list-tasks --cluster "$APP_NAME" --desired-status RUNNING --region "$AWS_REGION" --profile "$AWS_PROFILE" --query 'taskArns[-1]' --output text)
    if [ "$TASK_ARN" != "None" ]; then
        break
    fi
    echo "  待機中... ($i/36)"
    sleep 5
done

if [ "$TASK_ARN" = "None" ]; then
    echo "❌ タスクが起動しませんでした"
    exit 1
fi

# パブリックIP取得
echo "🌐 パブリックIP取得中..."
ENI=$(aws ecs describe-tasks --cluster "$APP_NAME" --tasks "$TASK_ARN" --region "$AWS_REGION" --profile "$AWS_PROFILE" --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value | [0]" --output text)
PUB=$(aws ec2 describe-network-interfaces --network-interface-ids "$ENI" --region "$AWS_REGION" --profile "$AWS_PROFILE" --query 'NetworkInterfaces[0].Association.PublicIp' --output text)

echo "🎉 デプロイ完了!"
echo "📍 パブリックIP: $PUB"
echo "🔗 API URL: http://$PUB:8080"
echo "📋 テストコマンド:"
echo "curl -X POST \"http://$PUB:8080/api/v1/pcb/generate-design-data\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"switches\":[{\"x_mm\":100,\"y_mm\":100,\"rotation_deg\":0,\"ref\":\"SW1\",\"size\":24}],\"units\":\"mm\"}' \\"
echo "  -o \"routed_project.zip\""

# 一時ファイル削除
rm -f /tmp/td-current.json /tmp/td-new.json

echo "✨ デプロイスクリプト完了"
