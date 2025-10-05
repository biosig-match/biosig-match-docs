---
service_name: "Processor Service"
description: "Collectorから転送された生のセンサーデータを処理し、非圧縮の状態で永続化するバックエンドサービス。"

inputs:
  - source: "RabbitMQ (bound to raw_data_exchange)"
    data_format: "AMQP Message"
    schema: |
      Queue: processing_queue
      Body: Zstandard-compressed binary data
      Headers: { "user_id": "string" }

outputs:
  - target: "MinIO"
    data_format: "Raw Binary Data"
    schema: "zstd伸長後の生のバイナリデータ。オブジェクトのメタデータに `X-Compression: 'none'` が設定される。"
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: "`raw_data_objects`テーブルに、object_id, user_id, device_id, start_time_device, end_time_deviceを記録。"
---

## 概要

`Processor`は、`Collector`サービスによって`raw_data_exchange`へ発行された生のセンサーデータメッセージを受け取り、永続化を行う非同期ワーカーです。主な責務は、**受信したzstd圧縮済みバイナリデータを伸長し、生の（非圧縮）バイナリデータのままオブジェクトストレージへ格納し、そのメタデータをデータベースへ記録する**ことです。

## 詳細

-   **責務**: **「受信した生データを非圧縮の状態で永続化し、後続のサービスが直接利用できる形に整えること」**。

-   **データ永続化の思想**: 本サービスは、後続のサービス（`BIDS Exporter`や`Event Corrector`など）が都度zstd伸長を行うオーバーヘッドをなくすため、**非圧縮のバイナリデータ**をMinIOに保存します。これにより、後段のサービスはデータフォーマットを意識することなく、純粋なバイナリパース処理に集中できます。

### 処理フロー (Asynchronous Worker)

1.  **メッセージ受信**: `raw_data_exchange`にバインドされた`processing_queue`からメッセージを一つ取り出します。メッセージヘッダーに`user_id`が含まれていることが必須です。
2.  **データ伸長**: メッセージボディ（zstd圧縮データ）を、Zstandard WASMモジュールを使ってメモリ上で伸長します。
3.  **メタデータ抽出**: 伸長後の生のバイナリデータをパースし、以下の情報を抽出します。
    -   `deviceId`: ヘッダー（最初の18バイト）から抽出されるデバイス識別子。
    -   `startTime`, `endTime`: データポイント群の最初と最後のタイムスタンプ（32-bit符号なし整数、デバイスティック）を抽出。
4.  **オブジェクトID生成**: 抽出したメタデータに基づき、自己記述的なオブジェクトIDを以下の形式で生成します。
    -   **形式**: `raw/{user_id}/start_tick={start_time}/end_tick={end_time}_{uuid}.zst`
    -   **注**: 拡張子は`.zst`ですが、格納されるデータ自体は**非圧縮**です。これは命名規則の一貫性のための可能性があります。
5.  **MinIOへのアップロード**: **伸長後の生のバイナリデータ**を、生成したオブジェクトIDでMinIOの`raw_data_bucket`にアップロードします。その際、MinIOオブジェクトのメタデータとして`X-Compression: 'none'`を設定し、データが非圧縮であることを明示します。
6.  **データベースへの記録**: `raw_data_objects`テーブルに、`object_id`, `user_id`, `device_id`、およびデバイスティックとしての`start_time_device`と`end_time_device`を`INSERT`します。
7.  **メッセージ確認**: 処理が成功するとメッセージを`ack`してキューから削除します。エラー発生時は、一時的なエラー（DB接続断など）か恒久的なエラー（データパース不能など）かを判別し、前者ならリキュー、後者なら破棄します。

### APIエンドポイント

本サービスは主に非同期ワーカーとして動作しますが、デバッグ用のHTTPエンドポイントも提供しています。

-   `POST /api/v1/inspect`
    -   **目的**: 生データパケットの中身を簡単に確認するためのデバッグ用ツール。
    -   **リクエストボディ**: `{"payload_base64": "..."}` (zstd圧縮され、Base64エンコードされたデータ文字列)
    -   **処理**: 受信したデータをBase64デコードし、zstd伸長を行った後、メタデータ（`deviceId`, `startTime`, `endTime`）を抽出し、伸長後のデータサイズと共にJSON形式で返します。
    -   **レスポンス (例)**: `{"deviceId": "...", "startTime": ..., "endTime": ..., "decompressed_size": ...}`

---

## スキーマ変更に伴う修正要件

新しいデータスキーマに対応するため、`Processor`の処理フローは大幅な変更が必要です。

### 0. 前提条件: データベーススキーマの変更

**警告:** 以下に記述されているコードの修正を適用する前に、`raw_data_objects`テーブルのスキーマを必ず変更する必要があります。この変更を行わない場合、`Processor`サービスはデータベースへの書き込みに失敗し、ランタイムエラーで停止します。

**実行すべきSQL:**

```sql
-- 既存の古いカラムを削除
ALTER TABLE raw_data_objects
  DROP COLUMN IF EXISTS start_time,
  DROP COLUMN IF EXISTS end_time,
  DROP COLUMN IF EXISTS start_time_device,
  DROP COLUMN IF EXISTS end_time_device;

-- 新しいスキーマ仕様に合わせたカラムを追加
ALTER TABLE raw_data_objects
  ADD COLUMN IF NOT EXISTS session_id VARCHAR(255),
  ADD COLUMN IF NOT EXISTS timestamp_start_ms BIGINT,
  ADD COLUMN IF NOT EXISTS timestamp_end_ms BIGINT;

-- パフォーマンス向上のためのインデックスを追加
CREATE INDEX IF NOT EXISTS idx_raw_data_objects_session ON raw_data_objects (session_id);
CREATE INDEX IF NOT EXISTS idx_raw_data_objects_timestamps ON raw_data_objects (timestamp_start_ms, timestamp_end_ms);
```

このデータベースマイグレーションは、後続の`BIDS Exporter`や`Event Corrector`など、多くのサービスが正しく機能するための必須条件です。

### 1. AMQPメッセージの入力仕様変更

`Collector`から受け取るAMQPメッセージのヘッダーに、複数のフィールドが追加されます。

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
  - サービスはこれらの新しいヘッダーをすべて読み込む必要があります。

### 2. メタデータ抽出ロジックの変更

これまでバイナリデータから抽出していた`deviceId`, `startTime`, `endTime`は、**AMQPメッセージヘッダーから取得**するように変更します。バイナリデータのパースは不要になります。

- **旧処理:** バイナリをパースしてメタデータを抽出する。
- **新処理:** `device_id`, `timestamp_start_ms`, `timestamp_end_ms`をヘッダーから直接取得する。

### 3. バイナリデータの取り扱い

- サービスは引き続きzstd伸長を行いますが、伸長後のバイナリデータの中身をパースしてメタデータを抽出する必要はなくなります。
- 伸長後のデータは、そのままMinIOにアップロードします。
- **（任意）** 新しいバイナリ構造（ヘッダーブロック＋サンプルデータブロック）が仕様通りであるか、基本的な検証（例：バージョン番号の確認）を行うことが推奨されます。

### 4. MinIOオブジェクトIDの命名規則変更

オブジェクトIDの命名規則を、ヘッダーから取得したミリ秒単位のタイムスタンプを使用するように変更します。

- **新形式（推奨）:** `raw/{user_id}/start_ms={timestamp_start_ms}/end_ms={timestamp_end_ms}_{device_id}_{uuid}.bin`
  - 拡張子を`.bin`などに変更し、非圧縮であることを明確にすることが望ましいです。

### 5. データベースへの記録内容の変更

`raw_data_objects`テーブルへの記録内容を、ヘッダーから取得した情報に更新します。

- **`device_id`**: ヘッダーから取得した値を使用します。
- **`start_time_device`, `end_time_device`**: ヘッダーの`timestamp_start_ms`, `timestamp_end_ms`を記録するように変更します。カラム名も`start_time_ms`, `end_time_ms`などに変更することが推奨されます。
- **`session_id`の追加**: 
  - `raw_data_objects`テーブルに`session_id`カラム（`string`, nullable）を追加する必要があります。
  - ヘッダーから取得した`session_id`をこの新しいカラムに保存します。

### 6. デバッグAPI (`/api/v1/inspect`) の修正

このエンドポイントは現在、バイナリからメタデータを抽出・返却しますが、このロジックは機能しなくなります。新しいスキーマに対応させるためには、以下のような修正が考えられます。

- `payload_base64`に加えて、`user_id`, `session_id`などのメタデータもリクエストボディで受け取るように変更する。
- レスポンスとして、zstd伸長・パース後の詳細なデータ構造（例：チャンネル数、電極設定、サンプルの一部）を返すように修正する。