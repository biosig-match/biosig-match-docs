---
service_name: "ERP Neuro-Marketing Service"
component_type: "service"
description: "BIDS Exporter と連携して ERP 解析を実行し、推奨刺激のリストと要約を返す FastAPI ベースの解析サービス。"
inputs:
  - source: "Web / 内部クライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/neuro-marketing/experiments/:experiment_id/analyze
      Headers: X-User-Id (owner 必須)
      Body: なし
  - source: "Auth Manager Service"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST {AUTH_MANAGER_URL}/api/v1/auth/check
      Body: { user_id: string, experiment_id: uuid, required_role: 'owner' }
      用途: verify_owner_role 依存性での権限チェック
  - source: "BIDS Exporter Service"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST {BIDS_EXPORTER_URL}/internal/v1/create-bids-for-analysis
      Body: { experiment_id: uuid }
      レスポンス: { bids_path: string }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: |
      - sessions (event_correction_status='completed')
      - session_events
      - experiment_stimuli (item_name, brand_name, category, gender)
outputs:
  - target: "HTTP クライアント"
    data_format: "JSON"
    schema: |
      AnalysisResponse:
        experiment_id: uuid
        recommendations: [{ file_name, item_name?, brand_name?, description?, category?, gender? }]
        summary: string
  - target: "ログ"
    data_format: "構造化ログ"
    schema: |
      INFO/ERROR ログを標準出力へ。解析手順・外部 API の失敗を記録。
---

## 概要

ERP Neuro-Marketing Service は FastAPI で提供される単一の公開エンドポイントを持ち、ERP/感情スペクトラム解析を行います。`verify_owner_role` 依存性により `Auth Manager Service` へ権限を確認し、許可された場合は BIDS Exporter に内部 API 経由でデータセット生成を依頼、得られた BIDS データを用いて解析パイプラインを実行します。

主な実装ファイル:

- `erp_neuro_marketing/src/app/server.py` : FastAPI ルーティング。
- `erp_neuro_marketing/src/app/dependencies/auth.py` : 権限チェック。
- `erp_neuro_marketing/src/domain/analysis/orchestrator.py` : 解析パイプライン本体。

## ランタイム構成

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | 解析に必要なメタデータ取得。 |
| `BIDS_EXPORTER_URL` | 内部 API 呼び出し先。 |
| `AUTH_MANAGER_URL` | 権限チェック先。 |
| `SHARED_VOLUME_PATH` | BIDS データ生成・モデル保存先。 |
| `GEMINI_API_KEY` | 生成 AI 要約 (任意)。 |

## 解析フロー

1. **認可**: `verify_owner_role` が `Auth Manager` の `/api/v1/auth/check` を呼び出し、`owner` ロールを確認。403/404 を透過して返却。
2. **セッション・刺激メタデータ取得**: `_load_experiment_metadata` が PostgreSQL から完了済みセッションと刺激情報を取得。キャリブレーション/本番セッションが不足している場合は 404。
3. **BIDS データ生成**: `request_bids_creation` が BIDS Exporter の内部 API を呼び出し、`bids_path` を受領。生成失敗時は 503。
4. **前処理**: `create_epochs_from_bids` が calibration / main セッションごとの MNE Epochs を作成。
5. **モデル学習**: `ErpDetector` がキャリブレーションデータから分類器を構築。
6. **推定**: `EmoSpecEstimator` が本番データに対して推定を実行し、反応が強かった刺激 (`prediction == 1`) を抽出。
7. **推奨リスト組み立て**: `experiment_stimuli` メタデータと突合し、`recommendations` を作成。
8. **要約生成**: `generate_ai_summary` が Gemini API (任意) で自然言語サマリーを作成。未設定の場合は定型文を返す。

## API 仕様

### `POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze`

| 項目 | 内容 |
| --- | --- |
| ヘッダー | `X-User-Id` (owner 権限を要求)。 |
| 入力ボディ | なし。 |
| 成功レスポンス | `AnalysisResponse` JSON。 |
| 失敗レスポンス |
  - 401: `X-User-Id` 欠如。
  - 403 / 404: 権限 or 実験関連データ不足。
  - 503: Auth/BIDS Exporter など外部サービス障害。
  - 500: 想定外エラー。 |

## 解析結果フォーマット

| フィールド | 説明 |
| --- | --- |
| `recommendations` | 刺激ファイル単位の推奨リスト。`experiment_stimuli` の `file_name`, `item_name`, `brand_name`, `description`, `category`, `gender` が含まれる。 |
| `summary` | Gemini API もしくはフォールバックメッセージによる解析要約文。 |

## 参考ファイル

- 依存解決: `erp_neuro_marketing/src/app/dependencies/auth.py`
- 解析モデル: `erp_neuro_marketing/src/domain/analysis/models.py`
- BIDS クライアント: `erp_neuro_marketing/src/infrastructure/bids_client.py`
