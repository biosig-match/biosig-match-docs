---
service_name: "Processor Service"
component_type: "service"
description: "Collector から配信された圧縮バイナリを復号し、MinIO と PostgreSQL に永続化する非同期ワーカー兼デバッグ API。"
inputs:
  - source: "RabbitMQ exchange raw_data_exchange"
    data_format: "AMQP message"
    schema: |
      Queue: config.PROCESSING_QUEUE (fanout バインド)
      Headers:
        user_id: string
        device_id: string
        timestamp_start_ms: integer
        timestamp_end_ms: integer
        sampling_rate: number
        lsb_to_volts: number
        session_id?: string
      Body: zstd 圧縮バイナリ (payload format v4)
  - source: "HTTP クライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/inspect
      Body:
        payload_base64: string
        sampling_rate: number
outputs:
  - target: "MinIO (raw-data bucket)"
    data_format: "Object PUT"
    schema: |
      Key: raw/{user_id}/{device_id}/start_ms={timestamp_start_ms}/end_ms={timestamp_end_ms}_{uuid}.bin
      Metadata:
        Content-Type: application/octet-stream
        X-User-Id, X-Device-Id, X-Sampling-Rate, X-Lsb-To-Volts, X-Session-Id?
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: |
      INSERT raw_data_objects (
        object_id,
        user_id,
        device_id,
        session_id,
        start_time,
        end_time,
        timestamp_start_ms,
        timestamp_end_ms,
        sampling_rate,
        lsb_to_volts
      )
      ON CONFLICT DO NOTHING
  - target: "監視クライアント"
    data_format: "HTTP JSON"
    schema: |
      GET /api/v1/health -> { status, rabbitmq_connected, db_connected, last_rabbit_connected_at?, timestamp }
      GET /health -> { status }
---

## 概要

Processor は Bun + Hono で実装されたサービスで、実際の仕事は RabbitMQ コンシューマです。起動すると Zstandard WASM を初期化し (`ensureZstdReady`)、MinIO バケットの存在確認 (`ensureMinioBucket`) と RabbitMQ への接続 (`connectRabbitMQ`) を行い、`processMessage` でメッセージを処理します。HTTP ポートはデバッグ (`/api/v1/inspect`) とヘルスチェック専用です。

## サービスの役割と主なユースケース

- **生体信号の永続化パイプライン**: Collector から届く圧縮バイナリを解凍し、MinIO と PostgreSQL の双方へメタデータとともに保存します。これにより後続の解析・エクスポートが raw データにアクセスできるようになります。
- **フォーマット検証と可観測性**: `/api/v1/inspect` に Base64 を投げるだけで、チャネル構成・サンプル数・トリガ有無などを可視化できます。実験前後のデバッグや新しいファームウェアの検証に利用されます。
- **耐障害性**: MinIO / DB / RabbitMQ への書き込みが失敗した場合でも、再キュー (requeue) によりメッセージを失わずに処理を再試行します。ネットワーク障害の回復後も継続的に処理できる設計です。
- **オブジェクト管理の標準化**: オブジェクトキーが `raw/{user}/{device}/start_ms=...` 形式に統一されるため、運用者は時間帯やデバイスで容易に検索・削除できます。

## ランタイム構成

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `DATABASE_URL` | 必須 | PostgreSQL 接続。 |
| `RABBITMQ_URL` | 必須 | AMQP 接続。 |
| `RAW_DATA_EXCHANGE` | `raw_data_exchange` | Fanout exchange 名。 |
| `PROCESSING_QUEUE` | `processing_queue` | バインドするキュー名。 |
| `MINIO_*` | - | `raw-data` バケットへの接続設定。 |
| `PORT` | `3010` | HTTP インターフェイス。 |

## RabbitMQ → MinIO/DB 処理フロー (`processMessage`)

1. ヘッダーから `user_id`, `device_id`, `timestamp_start_ms`, `timestamp_end_ms`, `sampling_rate`, `lsb_to_volts`, `session_id?` を取得。必須項目が揃わないメッセージは破棄 (ack)。
2. メッセージボディ (zstd 圧縮) を展開し、`Buffer` 化。
3. オブジェクト ID を `raw/{user}/{device}/start_ms=.../end_ms=..._{uuid}.bin` として生成。
4. MinIO `putObject` で生データを保存。メタデータにヘッダー値を設定。
5. `raw_data_objects` テーブルにメタデータを `INSERT`。`session_id` はこの段階では null (DataLinker が後処理)。`start_time` / `end_time` は null、`timestamp_*` にヘッダー値を格納。
6. 処理成功で ack。ネットワーク等の一時エラー (`isTransientError`) は nack requeue。

## `/api/v1/inspect`

- バリデーション: `inspectSchema` (`payload_base64`, `sampling_rate`)。
- 処理: Base64 → zstd 展開 → `inspectBinaryPayload` でヘッダ解析。
- レスポンス例:
  ```json
  {
    "inspection_result": {
      "header": {
        "version": 4,
        "num_channels": 16,
        "electrode_config": [{"name":"Fp1","type":0}, ...]
      },
      "payload_info": {
        "header_size_bytes": 180,
        "sample_size_bytes": 43,
        "num_samples_found": 256,
        "expected_samples": 256
      }
    },
    "decompressed_size": 11008
  }
  ```

## ヘルスチェック

| エンドポイント | 内容 |
| --- | --- |
| `GET /health` | RabbitMQ と DB をチェックし、どちらかが失敗すれば 503。 |
| `GET /api/v1/health` | 各接続状態を個別に返却 (degraded 判定あり)。 |

## グレースフルシャットダウン

`SIGINT` / `SIGTERM` で `shutdown` を呼び出し、コンシューマの cancel → チャネル・接続の close → DB プール解放を行います。

## 参考ファイル

- メッセージ処理: `processor/src/app/server.ts`
- Zstd 初期化: `@bokuweb/zstd-wasm`
- MinIO ラッパー: `minio` パッケージ
