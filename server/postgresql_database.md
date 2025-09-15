---
service_name: "PostgreSQL Database"
description: "全てのメタデータを管理する、信頼性の高いリレーショナルデータベース。システムにおける唯一の信頼できる情報源 (Single Source of Truth) です。"

inputs:
  - source: "Session Manager Service"
    data_format: "SQL INSERT/UPDATE/SELECT"
    schema: "`experiments`, `sessions`, `events`テーブルの操作"
  - source: "Media Processor Service"
    data_format: "SQL INSERT"
    schema: "`images`, `audio_clips`テーブルへのメタデータ書き込み"
  - source: "Processor Service"
    data_format: "SQL INSERT"
    schema: "`raw_data_objects`テーブルへのメタデータ書き込み"
  - source: "DataLinker Service"
    data_format: "SQL INSERT/UPDATE"
    schema: "`session_object_links`テーブルへの書き込み, `sessions`テーブルの`link_status`更新"

outputs:
  - target: "BIDS Exporter Service"
    data_format: "SQL SELECT"
    schema: "各種メタデータの読み出し"
  - target: "Session Manager Service"
    data_format: "SQL SELECT"
    schema: "各種メタデータの読み出し"
---

## 概要

PostgreSQL は、本システムにおける全ての構造化されたメタデータを管理します。実験、セッション、イベント、ユーザー情報、そして MinIO に保存された個々のデータオブジェクトへの参照（ポインタ）といった、データ間の関係性と一貫性を保証する役割を担います。

## スキーマ詳細

### `experiments` テーブル

実験の基本情報を管理します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `experiment_id` | UUID | **PK**, サーバーが発行する一意な実験 ID |
| `name` | VARCHAR(255) | NOT NULL, 実験名 |
| `description` | TEXT | 実験の詳細 |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW(), 作成日時 |

### `sessions` テーブル

計測セッションのメタデータを管理します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `session_id` | VARCHAR(255) | **PK**, スマホアプリが生成 (`{user_id}-{creation_unix_ms}`) |
| `user_id` | VARCHAR(255) | NOT NULL, ユーザー ID |
| `experiment_id` | UUID | NOT NULL, _FK to experiments_, 属する実験の ID |
| `device_id` | VARCHAR(255) | セッション終了時にアプリから送信されるデバイス ID |
| `start_time` | TIMESTAMPTZ | NOT NULL, セッション開始時刻(UTC) |
| `end_time` | TIMESTAMPTZ | セッション終了時刻(UTC), 終了時に更新される |
| `session_type` | VARCHAR(50) | 'calibration' または 'main' など |
| `link_status` | VARCHAR(50) | NOT NULL, DEFAULT 'pending', `DataLinker`の状態 |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW(), レコード作成日時 |

### `events` テーブル

セッション中に発生したイベント（例: 刺激呈示トリガー）を管理します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `id` | BIGSERIAL | **PK**, 自動採番 |
| `session_id` | VARCHAR(255) | NOT NULL, _FK to sessions_, 属するセッションの ID |
| `onset_s` | DOUBLE PRECISION | NOT NULL, セッション開始を 0 としたイベント発生時刻(秒) |
| `duration_s` | DOUBLE PRECISION | NOT NULL, イベントの継続時間(秒) |
| `description` | TEXT | イベントの説明 |
| `value` | VARCHAR(255) | イベントのカテゴリや値 |

### `raw_data_objects` テーブル

MinIO に保存された**圧縮済み**センサーデータ（EEG/IMU 混合）のメタデータを管理します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `object_id` | VARCHAR(512) | **PK**, MinIO のオブジェクトキー |
| `user_id` | VARCHAR(255) | NOT NULL, ユーザー ID |
| `device_id` | VARCHAR(255) | データパケットに含まれるデバイス ID |
| `start_time` | TIMESTAMPTZ | NOT NULL, データチャンクの開始時刻(UTC) |
| `end_time` | TIMESTAMPTZ | NOT NULL, データチャンクの終了時刻(UTC) |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW(), レコード作成日時 |

### `session_object_links` テーブル

`DataLinker`サービスによって、セッションとセンサーデータオブジェクトを紐付けるための中間テーブルです。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `session_id` | VARCHAR(255) | **PK**, _FK to sessions_ |
| `object_id` | VARCHAR(512) | **PK**, _FK to raw_data_objects_ |

### `images` / `audio_clips` テーブル

MinIO に保存されたメディアファイルのメタデータを管理します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `object_id` | VARCHAR(512) | **PK**, MinIO のオブジェクトキー |
| `user_id` | VARCHAR(255) | NOT NULL, ユーザー ID |
| `session_id` | VARCHAR(255) | **外部キー制約なし**。下記「設計思想」参照 |
| `experiment_id` | UUID | _FK to experiments_, `DataLinker`によって後から紐付け |
| `timestamp_utc` | TIMESTAMPTZ | NOT NULL, **(images のみ)** 撮影時刻 |
| `start_time` | TIMESTAMPTZ | NOT NULL, **(audio_clips のみ)** 録音開始時刻 |
| `end_time` | TIMESTAMPTZ | NOT NULL, **(audio_clips のみ)** 録音終了時刻 |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW(), レコード作成日時 |

## 設計思想とデータ関連付け戦略

1.  **メディアとセッションの非同期性**: `images`や`audio_clips`テーブルの`session_id`に外部キー制約を設けていません。これは、セッション中に送信されるメディアファイルの登録処理が、セッション終了時に行われる`sessions`テーブルへの登録処理よりも時間的に先行するためです。この柔軟性により、非同期なデータ投入を許容しています。

2.  **センサーデータオブジェクトの柔軟な管理**: `raw_data_objects`と`sessions`は、`session_object_links`中間テーブルを介して関連付けられます。これは、将来的に複数のデータパケットを単一のオブジェクトとして保存する可能性を考慮しているためです。この場合、1 つのオブジェクトがセッションの境界をまたぐ（例：セッション終了直前から次のセッション開始直後までのデータを含む）ことがあり得ます。中間テーブルを用いることで、このような多対多の関係を正確に表現できます。
