# Arcade Controller Design Project - Backend

FastAPI を使用したアーケードコントローラーデザインプロジェクトのバックエンド API

## プロジェクト構成

```
backend/
├── app/
│   └── src/
│       ├── __init__.py
│       ├── main.py              # FastAPIアプリケーションのエントリーポイント
│       ├── config.py            # アプリケーション設定
│       ├── routers/             # APIルーター
│       │   ├── __init__.py
│       │   └── health.py        # ヘルスチェックエンドポイント
│       ├── models/              # データモデル（将来の使用のため）
│       │   └── __init__.py
│       ├── schemas/             # Pydanticスキーマ
│       │   ├── __init__.py
│       │   └── base.py
│       ├── services/            # ビジネスロジック
│       │   └── __init__.py
│       └── utils/               # ユーティリティ関数
│           └── __init__.py
├── aws-config/                  # AWS設定ファイル
│   ├── taskdef.json            # ECSタスク定義テンプレート
│   └── README.md               # AWS設定ファイルの説明
├── scripts/                     # 開発用スクリプト
│   ├── dev.sh                   # 開発サーバー起動（Docker使用）
│   ├── dev-stop.sh              # 開発サーバー停止
│   ├── dev-logs.sh              # 開発サーバーログ確認
│   ├── dev-shell.sh             # 開発コンテナシェルアクセス
│   ├── format.sh                # コードフォーマット
│   └── lint.sh                  # リンティング
├── deploy.sh                    # AWS ECS Fargate デプロイスクリプト
├── Dockerfile                   # Dockerイメージ定義
├── pyproject.toml               # プロジェクト設定と依存関係
└── README.md
```

## 技術スタック

- **Framework**: FastAPI
- **ASGI Server**: Uvicorn
- **Package Manager**: uv
- **Linter/Formatter**: ruff
- **Validation**: Pydantic
- **Testing**: pytest (設定済み)

## セットアップ

### 必要な条件

- Python 3.12+
- uv (Python パッケージマネージャー)

### インストール

1. リポジトリをクローン:

   ```bash
   git clone <repository-url>
   cd arcade-controller-design-project/backend
   ```

2. 依存関係をインストール:

   ```bash
   uv sync
   ```

3. 環境変数を設定（オプション）:
   ```bash
   # .envファイルを作成（例）
   cat > .env << EOF
   APP_NAME="Arcade Controller Design Backend"
   APP_VERSION="0.1.0"
   DEBUG=true
   HOST="0.0.0.0"
   PORT=8000
   ALLOWED_ORIGINS=["http://localhost:3000", "http://127.0.0.1:3000"]
   DATABASE_URL="sqlite:///./arcade_controller.db"
   SECRET_KEY="your-secret-key-change-this-in-production"
   ALGORITHM="HS256"
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   EOF
   ```

## 開発

### サーバー起動

#### 開発環境（Docker 使用 - 推奨）

```bash
# 開発サーバー起動（本番環境と同じDocker環境）
./scripts/dev.sh

# 開発サーバー停止
./scripts/dev-stop.sh

# ログ確認
./scripts/dev-logs.sh

# コンテナ内シェルアクセス
./scripts/dev-shell.sh
```

**開発環境の特徴:**

- 本番環境と同じ Docker コンテナで動作
- KiCad と Freerouting が利用可能
- ホットリロード機能付き
- ポート 8080 で起動

#### 軽量開発環境（Docker 不使用）

```bash
# 直接uvicornを使用（KiCad/Freeroutingは使用不可）
uv run uvicorn app.src.main:app --reload --host 0.0.0.0 --port 8000
```

**注意:** 軽量環境では PCB 生成 API は動作しません。完全なテストには Docker 環境が必要です。

### コード品質

```bash
# リンティング
./scripts/lint.sh
# または
uv run ruff check app/

# フォーマット
./scripts/format.sh
# または
uv run ruff format app/
```

### テスト

```bash
uv run pytest
```

## API エンドポイント

### ヘルスチェック

- `GET /` - ルートエンドポイント
- `GET /api/v1/health/` - アプリケーションヘルスチェック

### API ドキュメント

- `GET /docs` - Swagger UI (開発モードのみ)
- `GET /redoc` - ReDoc (開発モードのみ)

## 開発ガイドライン

### コードスタイル

- ruff を使用して PEP 8 に準拠
- 型ヒントを使用
- docstring でドキュメント化

### ディレクトリ構造の説明

- `routers/`: FastAPI ルーターを配置
- `models/`: データベースモデルまたはビジネスモデル
- `schemas/`: Pydantic スキーマ（リクエスト/レスポンス）
- `services/`: ビジネスロジック
- `utils/`: 共通ユーティリティ関数

## 環境変数

| 変数名            | デフォルト値                                       | 説明                       |
| ----------------- | -------------------------------------------------- | -------------------------- |
| `APP_NAME`        | "Arcade Controller Design Backend"                 | アプリケーション名         |
| `APP_VERSION`     | "0.1.0"                                            | アプリケーションバージョン |
| `DEBUG`           | `true`                                             | デバッグモード             |
| `HOST`            | "0.0.0.0"                                          | サーバーホスト             |
| `PORT`            | `8000`                                             | サーバーポート             |
| `ALLOWED_ORIGINS` | ["http://localhost:3000", "http://127.0.0.1:3000"] | CORS 許可オリジン          |
| `DATABASE_URL`    | "sqlite:///./arcade_controller.db"                 | データベース URL           |
| `SECRET_KEY`      | "your-secret-key-change-this-in-production"        | JWT 秘密鍵                 |

## Docker 実行ベースライン（安定構成）

- ベースイメージ: `ghcr.io/kicad/kicad:9.0.4`（KiCad 9 系を保証。ビルド時に `pcbnew.GetBuildVersion()`で 9.x を検証）
- Java: Temurin JRE 21 を APT（Adoptium）で導入（Freerouting 2.x 要件）
- X 環境: コンテナ起動時の CMD では `xvfb-run` を使用しない（通常の FastAPI 起動）。KiCad 実行時のみアプリ内で `USE_XVFB=1` により `xvfb-run` を使用
- Python 依存: ビルダー段階で `/opt/site-packages` に展開し、本番段階で `PYTHONPATH=/opt/site-packages` を設定
- ポート: 8080 を公開。ECS の `entryPoint/command` は上書きせず Dockerfile の `CMD (python3 -m uvicorn ...)` を採用
- ヘルスチェック: ALB のパスは `/api/v1/health/` を推奨。ECS の `healthCheckGracePeriodSeconds` で起動直後の猶予を付与可

トラブルシュートの要点

- `java` が見つからない: 画像に JRE 21 が入っているか確認（`java -version`）
- KiCad API の X Display エラー: `USE_XVFB=1` が有効か、`xvfb` がインストール済みか確認
- OOM/137: `JAVA_TOOL_OPTIONS` の `-Xmx` を抑制、必要に応じて一時的にタスクメモリを引き上げ
- ALB ヘルスチェック失敗: パスを `/api/v1/health/` にし、interval/timeout と猶予の見直し

## デプロイ

### AWS ECS Fargate デプロイ

このプロジェクトは AWS ECS Fargate にデプロイされています。

#### デプロイスクリプト

コード修正後の再デプロイは `deploy.sh` スクリプトを使用して簡単に行えます：

```bash
# 基本的なデプロイ（タイムスタンプタグ）
./deploy.sh

# カスタムタグでデプロイ
./deploy.sh "feature-xyz"
```

#### デプロイスクリプトの機能

- Docker イメージのビルドと ECR へのプッシュ
- ECS タスク定義の自動更新
- サービスの強制再デプロイ
- パブリック IP の自動取得
- テスト用 curl コマンドの表示

#### 必要な AWS 権限

デプロイスクリプトを実行するには以下の AWS 権限が必要です：

- `AmazonEC2ContainerRegistryFullAccess`
- `AmazonECS_FullAccess`
- `CloudWatchLogsFullAccess`
- `AmazonEC2FullAccess`

#### 環境変数

デプロイ前に以下の環境変数を設定してください：

```bash
export AWS_PROFILE="your-aws-profile"  # デフォルト: new-acct
export AWS_REGION="ap-northeast-1"     # デフォルト: ap-northeast-1
```

#### デプロイ後の確認

デプロイ完了後、以下のコマンドで API の動作を確認できます：

```bash
# ヘルスチェック
curl http://<PUBLIC_IP>:8080/api/v1/health/

# PCB生成API テスト
curl -X POST "http://<PUBLIC_IP>:8080/api/v1/pcb/generate-design-data" \
  -H "Content-Type: application/json" \
  -d '{
    "switches": [
      {
        "x_mm": 100,
        "y_mm": 100,
        "rotation_deg": 0,
        "ref": "SW1",
        "size": 24
      }
    ],
    "units": "mm"
  }' \
  -o "routed_project.zip"
```

### AWS Lightsail（簡易・低コスト）

ECS を残したまま、Lightsail コンテナサービスへ同一 Docker イメージをデプロイできます。

手順:

```bash
# 必要: aws cli v2 でログイン済み、AWS_REGION 設定（例: ap-northeast-1）
export AWS_REGION=ap-northeast-1

# 1) デプロイスクリプト実行（初回はサービス自動作成）
./scripts/deploy-lightsail.sh

# 任意: サービス名/リソースは環境変数で調整
SERVICE_NAME=arcade-backend POWER=medium SCALE=1 ./scripts/deploy-lightsail.sh

# 2) 出力URLにアクセス
# 例: https://xxx.lightsail.aws.amazon.com/api/v1/health/
```

既定構成:

- ポート: 8080 公開（エンドポイント HTTP/ヘルスチェック `/api/v1/health/`）
- 環境変数: `USE_XVFB=1`, `PYTHONPATH=/opt/site-packages`, `JAVA_TOOL_OPTIONS=-Xms256m -Xmx1024m`
- リソース: `POWER=medium`（目安: 1 vCPU / 2 GB）

### API エンドポイント

#### PCB 生成関連

- `POST /api/v1/pcb/generate` - PCB 生成のみ
- `POST /api/v1/pcb/autoroute` - 自動配線のみ
- `POST /api/v1/pcb/apply-ses` - SES ファイル適用のみ
- `POST /api/v1/pcb/generate-design-data` - **統合 API（推奨）** - PCB 生成から配線まで一括実行

#### リクエスト形式

```json
{
  "switches": [
    {
      "x_mm": 100,
      "y_mm": 100,
      "rotation_deg": 0,
      "ref": "SW1",
      "size": 24
    }
  ],
  "units": "mm"
}
```

#### パラメータ説明

- `x_mm`, `y_mm`: ボタンの座標（ミリメートル）
- `rotation_deg`: ボタンの回転角度（度）
- `ref`: ボタンの参照名（SW1, SW2 など）
- `size`: ボタンサイズ（18, 24, 30 のいずれか）
- `units`: 単位（"mm"を推奨）

## 今後の拡張

- データベース統合（SQLAlchemy, Alembic）
- 認証・認可システム
- API バージョニング
- ログシステム
- パフォーマンス最適化
