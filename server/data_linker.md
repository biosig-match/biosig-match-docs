---
service_name: "DataLinker Service"
component_type: "service"
description: "セッション終了後に実行される非同期ジョブを処理し、raw データ・メディアをセッションと実験に結び付けた上で Event Corrector を起動する。"
inputs:
  - source: "RabbitMQ queue data_linker_queue"
    data_format: "AMQP message (JSON)"
    schema: |
      { session_id: string }
  - source: "HTTP クライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/jobs
      Body: { session_id: string }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: |
      - sessions
      - raw_data_objects (timestamp_start_ms, timestamp_end_ms, sampling_rate, lsb_to_volts)
      - images / audio_clips
outputs:
  - target: "PostgreSQL"
    data_format: "SQL UPDATE/INSERT"
    schema: |
      - UPDATE sessions SET link_status, event_correction_status
      - UPDATE raw_data_objects SET start_time, end_time, session_id
      - INSERT session_object_links(session_id, object_id)
      - UPDATE images / audio_clips SET experiment_id (セッションに experiment_id が存在する場合のみ)
  - target: "RabbitMQ queue event_correction_queue"
    data_format: "AMQP message (JSON)"
    schema: |
      { session_id: string }
  - target: "監視クライアント"
    data_format: "HTTP JSON"
    schema: |
      GET /api/v1/health -> { status, rabbitmq_connected, db_connected, queue, timestamp }
---

## 概要

DataLinker は Bun で実装されたワーカー兼 HTTP API です。`Session Manager` がセッション完了後に投入する `{ session_id }` ジョブを処理し、以下を行います:

1. 対象セッションを `processing` → 成功時 `completed` / 失敗時 `failed` に更新。
2. 未リンクの `raw_data_objects` をセッション時間帯で探索し、UTC 時刻を補完 (`timestamp_*_ms` → `start_time`/`end_time`) しつつ `session_id` を設定。
3. 対象オブジェクトを `session_object_links` テーブルに登録。
4. `images` / `audio_clips` の `experiment_id` をセッションの `experiment_id` へ更新。
5. 後続の `Event Corrector` キューに `{ session_id }` を送信。

コードは `data_linker/src/app/server.ts` (HTTP) と `data_linker/src/domain/services/linker.ts` (ドメインロジック) に分かれています。

## ランタイム構成

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `DATABASE_URL` | 必須 | PostgreSQL 接続。 |
| `RABBITMQ_URL` | 必須 | AMQP 接続。 |
| `DATA_LINKER_QUEUE` | `data_linker_queue` | ジョブ取得キュー。 |
| `EVENT_CORRECTION_QUEUE` | 必須 | 後続キュー名。 |
| `PORT` | `3030` | HTTP インターフェイス。 |

## ジョブ処理手順 (`handleLinkerJob`)

1. トランザクション開始 (`BEGIN`)。
2. `sessions` から対象セッションを取得。存在しない場合はエラー。
3. `sessions.link_status` を `processing` にセット。
4. `linkRawDataToSession`:
   - セッションの `start_time` / `end_time` を中心に ±2000ms の範囲で `raw_data_objects` を検索。
   - 各オブジェクトの `timestamp_start_ms` / `timestamp_end_ms` を ISO8601 に変換し、`start_time` / `end_time` 列へ更新、`session_id` も設定。
   - `session_object_links` に `(session_id, object_id)` を UPSERT。
5. `linkMediaToExperiment`:
   - セッションに `experiment_id` が設定されている場合のみ実行。`images` / `audio_clips` で `session_id` が一致し `experiment_id` が NULL のレコードに対し、セッションの `experiment_id` を設定。
6. `link_status` を `completed` に更新。
7. `event_correction_queue` へ `{ session_id }` を送信 (RabbitMQ チャンネルは `data_linker/src/infrastructure/queue.ts`)。
8. コミット。失敗時は `ROLLBACK` の上 `link_status='failed'` に更新。

## HTTP エンドポイント

| メソッド | パス | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/jobs` | 手動でジョブをキューに投入。RabbitMQ チャンネル未準備時は 503。 |
| `GET` | `/api/v1/health` | RabbitMQ / DB の状態と使用キュー名を返却。 |
| `GET` | `/health` | シンプルヘルスチェック。 |

## 参考ファイル

- キュー制御: `data_linker/src/infrastructure/queue.ts`
- ドメインロジック: `data_linker/src/domain/services/linker.ts`
- スキーマ定義: `data_linker/src/app/schemas/job.ts`
