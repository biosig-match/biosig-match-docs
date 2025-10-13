---
service_name: "Media Processor Service"
component_type: "service"
description: "Collector からキューイングされた画像・音声を MinIO へ保存し、メタデータを PostgreSQL に登録するコンシューマ。"
inputs:
  - source: "RabbitMQ queue media_processing_queue"
    data_format: "AMQP message"
    schema: |
      Headers:
        user_id: string
        session_id: string
        mimetype: string
        original_filename: string
        timestamp_utc?: ISO8601 (image必須)
        start_time_utc?: ISO8601 (audio必須)
        end_time_utc?: ISO8601 (audio必須)
      Body: バイナリファイル (画像 or 音声)
  - source: "HTTP クライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/preview-object-id
      Body:
        user_id: string
        session_id: string
        mimetype: string
        original_filename: string
        timestamp_utc?: string
        start_time_utc?: string
        end_time_utc?: string
outputs:
  - target: "MinIO (media bucket)"
    data_format: "Object PUT"
    schema: |
      Key: media/{user_id}/{session_id}/{timestampMs}_{photo|audio}{extension}
      Metadata:
        Content-Type, X-User-Id, X-Session-Id, X-Original-Filename
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: |
      - 画像: INSERT INTO images(object_id,user_id,session_id,experiment_id?,timestamp_utc)
      - 音声: INSERT INTO audio_clips(object_id,user_id,session_id,experiment_id?,start_time,end_time)
      (ON CONFLICT (object_id) DO NOTHING)
  - target: "監視クライアント"
    data_format: "HTTP JSON"
    schema: |
      GET /api/v1/health -> { status, rabbitmq_connected, db_connected, minio_connected, last_rabbit_connected_at?, timestamp }
      GET /health -> { status }
---

## 概要

Media Processor は Bun ベースの常駐コンシューマで、`media_processing_queue` から受信したメディアファイルを MinIO の `media` バケットに保存し、`images` / `audio_clips` テーブルへメタデータを登録します。HTTP インターフェイスはプレーンなオブジェクト ID のプレビュー計算とヘルスチェックのみを提供します。

## ランタイム構成

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 接続。 |
| `RABBITMQ_URL` | AMQP 接続。 |
| `MEDIA_PROCESSING_QUEUE` | コンシュームするキュー名。 |
| `MEDIA_PREFETCH` | `channel.prefetch` で設定する同時処理数。 |
| `MINIO_*` | MinIO 接続設定 (`MINIO_MEDIA_BUCKET` は既定 `media`)。 |

## メッセージ処理 (`processMessage`)

1. ヘッダーを `mediaMetadataSchema` で検証。画像は `timestamp_utc` 必須、音声は `start_time_utc` と `end_time_utc` 必須。
2. オブジェクト ID を `media/{user_id}/{session_id}/{timestampMs}_{photo|audio}{ext}` の形式で生成。
3. MinIO に `putObject` し、メタデータ (`X-User-Id` 等) を付加。
4. `mimetype` が `image/*` の場合は `images` テーブルへ挿入、`audio/*` の場合は `audio_clips` へ挿入。両テーブルとも `session_id` を保持し、`experiment_id` は後続の `DataLinker` が設定します。
5. 正常終了で ack。例外は `nack` + 再キュー。

## `/api/v1/preview-object-id`

- 入力: RabbitMQ と同じメタデータ JSON。
- 返却: `object_id` のみを返す (`{ "object_id": string }`)。
- ファイル本体不要のため、アップロード前にクライアントが保存パスを把握する用途に利用可能。

## ヘルスチェック

- `GET /health`: RabbitMQ, DB, MinIO の接続を順に確認し、いずれかが失敗すると 503。
- `GET /api/v1/health`: 各コンポーネントの状態を個別フラグで返却。

## 参考ファイル

- 実装: `media_processor/src/app/server.ts`
- スキーマ: `media_processor/src/app/server.ts` 内 `mediaMetadataSchema`
- 環境変数: `media_processor/src/config/env.ts`
