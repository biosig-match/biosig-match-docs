# Backend API Endpoints

各マイクロサービスが公開している HTTP エンドポイントを一覧化しています。権限要件・入力スキーマ・主な副作用を明記しているため、クライアント実装時のリファレンスとして利用してください。パスに `:id` が含まれる場合は実際の値で置き換えてください。

---

## Auth Manager Service (`auth_manager/src/app/routes/auth.ts`)

| メソッド | パス | 認可 | リクエスト | 副作用 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | 不要 | なし | DB 接続チェック。 |
| `GET` | `/api/v1/health` | 不要 | なし | サービス状態を JSON で返却。 |
| `POST` | `/api/v1/auth/experiments/:experiment_id/join` | 不要 | JSON `{ user_id: string, password?: string }` | `experiment_participants` に `role='participant'` で登録。実験にパスワードが設定されている場合は検証。 |
| `GET` | `/api/v1/auth/experiments/:experiment_id/participants` | `X-User-Id` (owner) | なし | 参加者一覧を返却。 |
| `PUT` | `/api/v1/auth/experiments/:experiment_id/participants/:user_id` | `X-User-Id` (owner) | JSON `{ role: 'owner' | 'participant' }` | 対象ユーザーのロールを更新。 |
| `POST` | `/api/v1/auth/check` | 内部利用 | JSON `{ user_id, experiment_id (uuid), required_role }` | 権限判定 `{ authorized: boolean }` を返却。 |

---

## Session Manager Service (`session_manager/src/app/routes/*.ts`)

| メソッド | パス | 認可 | リクエスト | 主な処理 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | なし | なし | DB 接続ヘルス。 |
| `GET` | `/api/v1/health` | なし | なし | DB / RabbitMQ 状態。 |
| `POST` | `/api/v1/experiments` | `X-User-Id` 必須 | JSON `{ name, description?, password?, presentation_order? }` | 実験作成、作成者を owner として登録。 |
| `GET` | `/api/v1/experiments` | `X-User-Id` 必須 | なし | 参加している実験一覧を返却。 |
| `POST` | `/api/v1/experiments/:experiment_id/stimuli` | owner | multipart: `stimuli_definition_csv`, `stimulus_files[]` | CSV/ファイルの整合性検証後、`stimulus_asset_queue` にジョブ投入。 |
| `GET` | `/api/v1/experiments/:experiment_id/stimuli` | participant 以上 | なし | 登録済み刺激一覧。 |
| `POST` | `/api/v1/experiments/:experiment_id/export` | owner | なし | BIDS Exporter へフォワード。 |
| `POST` | `/api/v1/sessions/start` | participant 以上 | JSON `{ session_id, user_id, experiment_id, start_time, session_type }` | セッションを `INSERT` (重複は無視)。 |
| `POST` | `/api/v1/sessions/end` | participant 以上 | multipart `metadata`(JSON) + `events_log_csv?` | セッション終了処理・CSV 取り込み・`data_linker_queue` へのジョブ投入。 |
| `GET` | `/api/v1/calibrations` | `X-User-Id` | なし | `calibration_items` を返却。 |
| `GET` | `/api/v1/stimuli/calibration/download/:filename` | `X-User-Id` | なし | MinIO からストリーム応答。 |
| `GET` | `/api/v1/stimuli/:experiment_id/download/:filename` | participant 以上 | なし | 実験刺激をストリームで返却。 |

---

## Collector Service (`collector/src/app/server.ts`)

| メソッド | パス | 認可 | リクエスト | 主な処理 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | なし | なし | RabbitMQ チャンネルチェック。 |
| `GET` | `/api/v1/health` | なし | なし | RabbitMQ 接続情報を返却。 |
| `POST` | `/api/v1/data` | なし | JSON `{ user_id, session_id?, device_id, timestamp_start_ms, timestamp_end_ms, sampling_rate, lsb_to_volts, payload_base64 }` | `raw_data_exchange` に fanout publish。payload は zstd 圧縮。 |
| `POST` | `/api/v1/media` | なし | multipart (file, user_id, session_id, mimetype, original_filename, timestamp_utc?/start_time_utc?/end_time_utc?) | `media_processing_queue` にバイナリを enqueue。 |

---

## Processor Service (`processor/src/app/server.ts`)

| メソッド | パス | 用途 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | ヘルス | なし | DB/RabbitMQ 状態。 |
| `GET` | `/api/v1/health` | 詳細ヘルス | なし | `rabbitmq_connected`, `db_connected` 等。 |
| `POST` | `/api/v1/inspect` | デバッグ | JSON `{ payload_base64, sampling_rate }` | 展開したメタ情報 (チャンネル構成、サンプル数など)。 |

> メインのデータ処理は `processing_queue` 消費によって行われます。

---

## Media Processor Service (`media_processor/src/app/server.ts`)

| メソッド | パス | 用途 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | ヘルス | なし | `status`。 |
| `GET` | `/api/v1/health` | 詳細ヘルス | なし | RabbitMQ/DB/MinIO フラグ。 |
| `POST` | `/api/v1/preview-object-id` | 事前確認 | JSON `{ user_id, session_id, mimetype, original_filename, timestamp_utc?/start_time_utc?/end_time_utc? }` | `{ object_id }`。 |

> キュー `media_processing_queue` をコンシュームし、MinIO/DB を更新します。

---

## Stimulus Asset Processor Service (`stimulus_asset_processor/src/app/server.ts`)

| メソッド | パス | 用途 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | ヘルス | なし | `status`。 |
| `GET` | `/api/v1/health` | 詳細ヘルス | なし | RabbitMQ/DB/MinIO 状態。 |
| `POST` | `/api/v1/jobs` | 管理者用 | JSON (StimulusAssetJobPayload) | キューにジョブを投入 (`202`). |

---

## DataLinker Service (`data_linker/src/app/server.ts`)

| メソッド | パス | 用途 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | ヘルス | なし | `status`。 |
| `GET` | `/api/v1/health` | 詳細ヘルス | なし | RabbitMQ/DB 状態。 |
| `POST` | `/api/v1/jobs` | 手動キュー投入 | JSON `{ session_id: string }` | `202 Accepted`。 |

---

## Event Corrector Service (`event_corrector/src/app/server.ts`)

| メソッド | パス | 用途 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | ヘルス | なし | `status`。 |
| `GET` | `/api/v1/health` | 詳細ヘルス | なし | RabbitMQ/DB/MinIO 状態。 |
| `POST` | `/api/v1/jobs` | 手動キュー投入 | JSON `{ session_id: string }` | `202 Accepted`。 |

---

## BIDS Exporter Service (`bids_exporter/src/app/server.py`)

| メソッド | パス | 認可 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | なし | なし | MinIO 接続状態。 |
| `POST` | `/api/v1/experiments/:experiment_id/export` | 上流で owner 判定 | なし | `202 Accepted` + `{ task_id, status_url }`。 |
| `GET` | `/api/v1/export-tasks/:task_id` | なし | なし | タスクステータス。 |
| `GET` | `/api/v1/export-tasks/:task_id/download` | なし | なし | BIDS ZIP をストリーム返却。 |
| `POST` | `/internal/v1/create-bids-for-analysis` | ERP サービスのみ想定 | JSON `{ experiment_id }` | `{ experiment_id, bids_path, message }`。 |

---

## ERP Neuro-Marketing Service (`erp_neuro_marketing/src/app/server.py`)

| メソッド | パス | 認可 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | なし | なし | `{ status: 'ok' }`。 |
| `POST` | `/api/v1/neuro-marketing/experiments/:experiment_id/analyze` | `X-User-Id` (owner) | なし | `AnalysisResponse` (推薦リスト + サマリー)。 |

---

## Realtime Analyzer Service (`realtime_analyzer/src/app/server.py`)

| メソッド | パス | 用途 | リクエスト | 応答 |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | ヘルス | なし | RabbitMQ 接続状態。 |
| `GET` | `/api/v1/users/:user_id/analysis` | 解析結果取得 | なし | 最新解析結果 (Base64 画像 + チャネル品質)。データ未準備時は 202。 |

---

## 補足

- すべての Bun/Hono ベースのサービスは `GET /` で稼働確認用のテキストを返す実装が含まれていますが、クライアントからの利用は想定していません。
- キュー投入系エンドポイント (`/api/v1/jobs`) は運用・検証用であり、通常の業務フローでは内部ワーカーのみがキューを消費します。
