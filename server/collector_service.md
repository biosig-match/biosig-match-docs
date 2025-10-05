---
service_name: "Collector Service"
description: "全生データ（センサー、画像、音声）の受信を一手に引き受ける、スケーラブルなAPIゲートウェイ。"

inputs:
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (application/json)"
    schema: |
      // Endpoint: POST /api/v1/data
      {
        "user_id": "string",
        "payload_base64": "string" // zstd-compressed binary data, base64-encoded
      }
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (multipart/form-data)"
    schema: |
      // Endpoint: POST /api/v1/media
      // Form parts:
      - file: (binary file data)
      - user_id: string
      - session_id: string
      - mimetype: string (e.g., 'image/jpeg', 'audio/m4a')
      - original_filename: string
      // Conditional timestamp fields:
      - timestamp_utc: string (ISO8601) // Required if mimetype starts with 'image/'
      - start_time_utc: string (ISO8601) // Required if mimetype is not an image
      - end_time_utc: string (ISO8601) // Required if mimetype is not an image

outputs:
  - target: "RabbitMQ (Fanout Exchange: raw_data_exchange)"
    data_format: "AMQP Message"
    schema: |
      Body: Binary data (the decoded zstd-compressed payload)
      Properties: {
        "persistent": true,
        "contentType": "application/octet-stream",
        "contentEncoding": "zstd",
        "timestamp": (Date.now()),
        "headers": {
          "user_id": "string"
        }
      }
  - target: "RabbitMQ (Queue: media_processing_queue)"
    data_format: "AMQP Message"
    schema: |
      Body: Binary file data
      Properties: {
        "persistent": true,
        "contentType": (from metadata.mimetype),
        "timestamp": (Date.now()),
        "headers": {
          "user_id": "string",
          "session_id": "string",
          "mimetype": "string",
          "original_filename": "string",
          "timestamp_utc": "string (optional)",
          "start_time_utc": "string (optional)",
          "end_time_utc": "string (optional)"
        }
      }
---

## 概要

`Collector`は、クライアント（主にスマートフォンアプリ）から送信される全てのデータを受け付ける唯一の窓口となるAPIゲートウェイです。データの種類に応じてエンドポイントを分け、受信したデータを検証し、対応するメッセージブローカー（RabbitMQ）へ迅速に転送します。本サービスはビジネスロジックを一切含まず、データの受信と転送に特化することで、高いスループットと信頼性を確保します。

-   **センサーデータ (`/api/v1/data`)**: Base64エンコードされたzstd圧縮済みバイナリデータを受信し、`raw_data_exchange`（Fanout Exchange）へ発行します。
-   **メディアデータ (`/api/v1/media`)**: メディアファイル（画像・音声）を`multipart/form-data`で受信し、`media_processing_queue`へ発行します。

## 詳細

-   **責務**: **「データの種類に応じた受信、厳格なバリデーション、そして後段サービスへの迅速かつ透過的な転送」**。

### APIエンドポイントと処理フロー

#### `POST /api/v1/data`

1.  **受信と検証**: `application/json`形式で`user_id`と`payload_base64`を含むリクエストを受信します。`zod`ライブラリを用いて、両フィールドが存在し、空でないことを検証します。
2.  **デコード**: `payload_base64`をBase64デコードしてバイナリデータに変換します。デコードに失敗した場合は`400 Bad Request`を返します。
3.  **発行**: デコードしたバイナリデータをメッセージボディとし、`raw_data_exchange`へ発行します。この際、AMQPメッセージには以下のプロパティが付与されます。
    -   `headers`: `{ user_id: ... }`
    -   `contentEncoding`: `zstd` （ペイロードがzstd圧縮済みであることを示す）
    -   `contentType`: `application/octet-stream`
    -   `persistent`: `true`
4.  **応答**: 成功すると`202 Accepted`を返します。

#### `POST /api/v1/media`

1.  **受信と検証**: `multipart/form-data`形式のリクエストを受信します。`file`パートと複数のメタデータパートが含まれていることを期待します。
2.  **メタデータ検証**: `zod`を用いてメタデータを厳格に検証します。特に以下のカスタムルールが適用され、違反した場合は`400 Bad Request`を返します。
    -   `mimetype`が`image/...`で始まる場合、`timestamp_utc`フィールドは**必須**です。
    -   `mimetype`が画像でない場合、`start_time_utc`と`end_time_utc`フィールドは**必須**です。
3.  **発行**: `file`パートのバイナリデータをメッセージボディとし、検証済みのメタデータを`headers`に含めて`media_processing_queue`へ発行します。
4.  **応答**: 成功すると`202 Accepted`を返します。

### エラーハンドリング

-   **`400 Bad Request`**: リクエストの形式が不正な場合（例: JSONパースエラー、Base64デコードエラー、`zod`によるバリデーション失敗）。
-   **`503 Service Unavailable`**: RabbitMQへの接続が確立されていない場合に返されます。

---

## スキーマ変更に伴う修正要件

新しいデータスキーマに対応するため、以下の修正が必要です。

### 1. API (`POST /api/v1/data`) の入力仕様変更

`Collector`が受信するJSONペイロードに新しいフィールドが追加されます。

**新しいリクエストボディ:**
```json
{
  "user_id": "string",
  "session_id": "string | null",
  "device_id": "string",
  "timestamp_start_ms": "integer",
  "timestamp_end_ms": "integer",
  "payload_base64": "string"
}
```

- **実装上の注意:**
  - `zod`による入力検証スキーマを更新し、`session_id`, `device_id`, `timestamp_start_ms`, `timestamp_end_ms` を正しく検証する必要があります。
  - `session_id`は `null` の場合があることに注意してください。

### 2. RabbitMQへの発行メッセージ仕様変更

後続のサービスが新しいメタデータを利用できるよう、受信した追加フィールドをAMQPメッセージのヘッダーに含めて転送する必要があります。

**新しいAMQPメッセージヘッダー:**
```javascript
{
  "headers": {
    "user_id": "string",
    "session_id": "string | null",
    "device_id": "string",
    "timestamp_start_ms": "integer",
    "timestamp_end_ms": "integer"
  }
}
```

- **実装上の注意:**
  - `raw_data_exchange`へメッセージを発行する際に、リクエストボディから受け取った`user_id`, `session_id`, `device_id`, `timestamp_start_ms`, `timestamp_end_ms`をすべてメッセージヘッダーにコピーしてください。