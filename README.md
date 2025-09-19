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
├── scripts/                     # 開発用スクリプト
│   ├── dev.sh                   # 開発サーバー起動
│   ├── format.sh                # コードフォーマット
│   └── lint.sh                  # リンティング
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

```bash
# スクリプトを使用
./scripts/dev.sh

# または直接uvicornを使用
uv run uvicorn app.src.main:app --reload --host 0.0.0.0 --port 8000
```

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

## 今後の拡張

- データベース統合（SQLAlchemy, Alembic）
- 認証・認可システム
- API バージョニング
- ログシステム
- Docker コンテナ化
