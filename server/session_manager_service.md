---
service_name: "Session Manager Service"
component_type: "service"
description: "実験・セッションのライフサイクル管理を担い、認可済みクライアントからの操作を RabbitMQ ジョブや外部サービス呼び出しへ橋渡しする。"
inputs:
  - source: "クライアント (スマホアプリ / Web)"
    data_format: "HTTP JSON / multipart/form-data"
    schema: |
      - POST /api/v1/experiments
        Body (JSON): { name: string, description?: string, password?: string(min:4), presentation_order?: 'sequential'|'random' }
      - POST /api/v1/sessions/end
        Body (multipart):
          metadata: JSON (session_end_metadata)
          events_log_csv?: CSV (列: onset,duration,trial_type,file_name?,description?,value?)
  - source: "Auth Manager Service"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/auth/check
      Body: { user_id: string, experiment_id: uuid, required_role: 'owner'|'participant' }
      用途: requireAuth ミドルウェアによるロール検証
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: |
      - experiments / experiment_participants / experiment_stimuli / sessions / session_events / calibration_items
      - 刺激ダウンロード時は experiment_stimuli.object_id を参照
  - source: "MinIO (media bucket)"
    data_format: "Object GET"
    schema: |
      - カリブレーション刺激: calibration_items.object_id
      - 実験刺激: experiment_stimuli.object_id
outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE/DELETE"
    schema: |
      - INSERT experiments, experiment_participants
      - INSERT sessions, UPDATE sessions(end_time, device_id, link_status)
      - INSERT session_events (CSV 取込時は該当セッションの既存レコードを DELETE 後に一括 INSERT)
  - target: "RabbitMQ (stimulus_asset_queue)"
    data_format: "AMQP message (JSON)"
    schema: |
      { experiment_id: uuid, csvDefinition: [{trial_type,file_name,description?}], files: [{fileName,mimeType,contentBase64}] }
  - target: "RabbitMQ (data_linker_queue)"
    data_format: "AMQP message (JSON)"
    schema: |
      { session_id: string }
  - target: "BIDS Exporter Service"
    data_format: "HTTP POST"
    schema: |
      POST /api/v1/experiments/:experiment_id/export (ヘッダー X-User-Id を透過)
  - target: "HTTP 応答"
    data_format: "JSON / ストリーム"
    schema: |
      - 刺激ダウンロード時は MinIO オブジェクトをストリーミング
      - API 各種のレスポンス JSON
---

## 概要

`Session Manager Service` は Hono で実装された REST API で、実験定義・セッション記録・刺激資産管理を司ります。全ての書き込み系操作は `requireAuth` / `requireUser` ミドルウェア (`session_manager/src/app/middleware/auth.ts`) で `Auth Manager Service` に照会した上で処理されます。RabbitMQ を用いた非同期連携により、重い処理は `Stimulus Asset Processor` と `DataLinker` に委譲します。

## ランタイム構成

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 接続 (
`session_manager/src/infrastructure/db.ts`). |
| `RABBITMQ_URL` | AMQP ブローカー接続。 |
| `STIMULUS_ASSET_QUEUE` / `DATA_LINKER_QUEUE` | 投入先キュー名。 |
| `AUTH_MANAGER_URL` | 権限チェック先エンドポイント。 |
| `BIDS_EXPORTER_URL` | BIDS エクスポート委譲先。 |
| `MINIO_*` | 刺激ファイル取得のための MinIO 接続設定。 |

## データベース利用

| テーブル | 操作 |
| --- | --- |
| `experiments` | 生成 (`INSERT`)、一覧取得 (`SELECT`)。 |
| `experiment_participants` | 実験作成時に owner を `INSERT`。 |
| `experiment_stimuli` | 刺激一覧照会、CSV の検証用 SELECT。 |
| `sessions` | `POST /sessions/start` で `INSERT`、`/end` で `UPDATE`。 |
| `session_events` | `POST /sessions/end` 時に該当セッションを DELETE した後、CSV から再構築。 |
| `calibration_items` | キャリブレーション一覧 / ダウンロードで参照。 |

## RabbitMQ との連携

- 刺激登録ジョブ: `config.STIMULUS_ASSET_QUEUE` に対し `Buffer.from(JSON.stringify(jobPayload))` を `persistent: true` で送信。
- セッション終了後のデータ紐付けジョブ: `config.DATA_LINKER_QUEUE` に `{ session_id }` を送信。

## ミドルウェア `requireAuth`

1. `X-User-Id` ヘッダーを確認。
2. パスパラメータ・JSON・multipart から `experiment_id` を抽出 (`metadata` 内の JSON も解析)。
3. `Auth Manager` に `required_role` を照会し、権限不足は 403、通信失敗は 503。

## ヘルスチェック

- `GET /health`: DB 接続のみチェック。
- `GET /api/v1/health`: DB と RabbitMQ の両方の状態、サービス名、タイムスタンプを返却。

## API 詳細

### `POST /api/v1/experiments`

| 項目 | 内容 |
| --- | --- |
| 必須ヘッダー | `X-User-Id` (作成ユーザー) |
| ボディ | `createExperimentSchema` (`session_manager/src/app/schemas/experiment.ts`) |
| 処理 | 実験を `INSERT`、パスワードは `Bun.password.hash` で保存。作成ユーザーを owner として `experiment_participants` に登録。 |
| レスポンス | 新規 `experiment_id` を含む JSON、201。 |

### `GET /api/v1/experiments`

| 項目 | 内容 |
| --- | --- |
| 必須ヘッダー | `X-User-Id` |
| 処理 | 参加している実験IDを `experiment_participants` から抽出し、`experiments` を `experiment_id = ANY(...)` で取得。 |

### `POST /api/v1/experiments/:experiment_id/stimuli`

| 項目 | 内容 |
| --- | --- |
| 権限 | owner |
| ボディ | multipart: `stimuli_definition_csv` (CSV), `stimulus_files` (複数 File)。 |
| CSV スキーマ | `stimulusCsvRowSchema`: 列 `trial_type`, `file_name`, `description?`。 |
| 検証 | CSV 内の `file_name` とアップロードされたファイル名の完全一致。Zod によるバリデーション。 |
| 処理 | ファイル内容を Base64 エンコードした配列と CSV をまとめ、`stimulus_asset_queue` に投入。 |
| レスポンス | 202 (非同期処理)。 |

### `GET /api/v1/experiments/:experiment_id/stimuli`

`experiment_stimuli` から `stimulus_id`, `file_name`, `stimulus_type`, `trial_type`, `description` を返却。

### `POST /api/v1/experiments/:experiment_id/export`

- owner 権限。
- `fetch` で `BIDS Exporter` の同名エンドポイントへフォワード。
- 呼び出し元の `X-User-Id` を透過。
- 上流のレスポンスステータスと本文をそのまま中継。

### `POST /api/v1/sessions/start`

| 項目 | 内容 |
| --- | --- |
| 権限 | participant 以上 |
| ボディ | `sessionStartMetadataSchema` (`session_manager/src/app/routes/sessions.ts` 内部で定義)。`session_id`, `user_id`, `experiment_id`, `start_time`, `session_type`。 |
| 処理 | `sessions` に `INSERT` (`ON CONFLICT DO NOTHING`)。 |

### `POST /api/v1/sessions/end`

| 項目 | 内容 |
| --- | --- |
| 権限 | participant 以上 |
| フォーム | `metadata` (JSON) + `events_log_csv` (任意)。 |
| `metadata` スキーマ | `sessionEndMetadataSchema`: `session_id`, `user_id`, `experiment_id`, `device_id`, `start_time`, `end_time`, `session_type`。 |
| CSV 行スキーマ | `eventLogCsvRowSchema`: `onset`(必須数値), `duration?`, `trial_type`, `file_name?`, `description?`, `value?`。 |
| 処理 |
  1.  トランザクション開始。
  2.  `sessions` の `end_time`, `device_id` を更新。
  3.  CSV があれば対象セッションの `session_events` を一括削除→再挿入。
     - 刺激名と `experiment_stimuli.file_name` を照合し `stimulus_id` を設定。
     - キャリブレーションセッションの場合は `calibration_items` から `calibration_item_id` を解決。
  4.  コミット後に `DataLinker` へ `{ session_id }` を enqueue。
| エラー処理 | CSV パースや Zod バリデーション失敗時は 400。ジョブ投入失敗時は 500 を返しつつログに警告。 |

### `GET /api/v1/calibrations`

`calibration_items` から `item_id`, `file_name`, `item_type`, `description` を返却。`requireUser` のみ適用。

### 刺激ダウンロード

- `GET /api/v1/stimuli/calibration/download/:filename`
- `GET /api/v1/stimuli/:experiment_id/download/:filename`

`minioClient.getObject` を用いて MinIO からストリーミングレスポンスを生成。MIME 判定は `resolveStimulusMime` (`session_manager/src/shared/utils/mime.ts`) を使用。

## 参考ファイル

- ルーティング: `session_manager/src/app/routes/*.ts`
- スキーマ定義: `session_manager/src/app/schemas/*.ts`
- RabbitMQ ラッパー: `session_manager/src/infrastructure/queue.ts`
- MinIO ラッパー: `session_manager/src/infrastructure/minio.ts`
