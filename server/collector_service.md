---
service_name: "Collector Service"
component_type: "service"
description: "スマホアプリから送られるセンサーデータとメディアを受け取り、RabbitMQ 経由で下流処理サービスへ配信する入口ゲートウェイ。"
inputs:
  - source: "スマホアプリ / エッジデバイス"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/data
      Body:
        user_id: string
        session_id?: string | null
        device_id: string
        timestamp_start_ms: integer
        timestamp_end_ms: integer
        sampling_rate: number
        lsb_to_volts: number
        payload_base64: base64-encoded zstd binary
  - source: "スマホアプリ / エッジデバイス"
    data_format: "HTTP POST (multipart/form-data)"
    schema: |
      POST /api/v1/media
      Fields:
        file: File
        user_id: string
        session_id: string
        mimetype: string
        original_filename: string
        timestamp_utc?: ISO8601 (image必須)
        start_time_utc?: ISO8601 (audio必須)
        end_time_utc?: ISO8601 (audio必須)
outputs:
  - target: "RabbitMQ exchange raw_data_exchange"
    data_format: "AMQP fanout message"
    schema: |
      Exchange: config.RAW_DATA_EXCHANGE (fanout)
      Headers:
        user_id, device_id, timestamp_start_ms, timestamp_end_ms,
        sampling_rate, lsb_to_volts, session_id?
      Body: zstd 圧縮バイナリ (Collector 側ではエラーチェックのみ)
  - target: "RabbitMQ queue media_processing_queue"
    data_format: "AMQP persistent message"
    schema: |
      Headers:
        user_id, session_id, mimetype, original_filename,
        timestamp_utc?, start_time_utc?, end_time_utc?
      Body: バイナリファイルの生データ
  - target: "監視クライアント"
    data_format: "HTTP JSON"
    schema: |
      ヘルスチェック:
        GET /health -> {status:'ok'|'unhealthy'}
        GET /api/v1/health -> {status, service, rabbitmq_connected, last_connected_at?}
---

## 概要

Collector は Bun + Hono で実装された単一サービスで、REST API 経由で受け取ったデータを RabbitMQ に仲介します。起動時に fanout exchange `raw_data_exchange` とキュー `media_processing_queue` を宣言し、接続切断時は自動再接続を試みます。実装は `collector/src/app/server.ts` に集約されています。

## ランタイム構成

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `RABBITMQ_URL` | なし (必須) | AMQP 接続 URL。 |
| `RAW_DATA_EXCHANGE` | `raw_data_exchange` | Fanout exchange 名。 |
| `MEDIA_PROCESSING_QUEUE` | `media_processing_queue` | メディア処理キュー名。 |
| `PORT` | `3000` | HTTP サーバーポート。 |

## `/api/v1/data` エンドポイント

- バリデーション: `dataSchema` (`collector/src/app/server.ts`) により全フィールドを Zod で検証。
- `payload_base64` は Base64 として decode 後、空バッファを拒否します。
- ヘッダー構築時に `session_id` が null の場合は省略。
- `channel.publish` を利用し、`persistent: true`, `contentType: 'application/octet-stream'`, `contentEncoding: 'zstd'` を設定。
- 成功時レスポンス: `202 Accepted` + `{ "status": "accepted" }`。

## `/api/v1/media` エンドポイント

- multipart を `c.req.parseBody()` で受信。
- `file` フィールド必須。その他のフォーム値を `mediaSchema` で検証。
- 画像 (`mimetype` が `image/*`) の場合 `timestamp_utc` が必須、音声 (`audio/*`) の場合 `start_time_utc` と `end_time_utc` が必須。
- RabbitMQ へ `sendToQueue` し、ヘッダーにメタデータを付与。`timestamp` プロパティはメッセージ生成時刻 (Unix ms)。

## ヘルス監視

- `GET /health`: チャネル存在チェックのみ。
- `GET /api/v1/health`: チャネル状態と最後に接続に成功した `last_connected_at` を返却。接続が無い場合は 503。

## エラーハンドリング

- `HTTPException` を捕捉し、定義済みレスポンスをそのまま返却。
- その他の例外は 500 + `{ "error": "Internal Server Error" }`。
- RabbitMQ 接続失敗時は指数バックオフで再試行 (`scheduleReconnect`)。

## 参考ファイル

- HTTP サーバー実装: `collector/src/app/server.ts`
- 環境変数バリデーション: `collector/src/config/env.ts`
