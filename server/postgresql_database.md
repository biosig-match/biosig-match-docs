---
service_name: "PostgreSQL Database"
description: "全てのメタデータを管理する、信頼性の高いリレーショナルデータベース。システムにおける唯一の信頼できる情報源 (Single Source of Truth) です。"

inputs:
  - source: "Session Manager Service"
    data_format: "SQL INSERT/UPDATE/SELECT"
    schema: "`experiments`, `sessions`, `experiment_stimuli`, `session_events`テーブル等の操作"
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

PostgreSQL は、本システムにおける全ての構造化されたメタデータを管理します。実験、セッション、刺激、イベント、ユーザー情報、そして MinIO に保存された個々のデータオブジェクトへの参照（ポインタ）といった、データ間の関係性と一貫性を保証する役割を担います。

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
| `session_type` | VARCHAR(50) | 'calibration', 'main_integrated' (アプリ内蔵), 'main_external' (外部連携) など |
| `link_status` | VARCHAR(50) | NOT NULL, DEFAULT 'pending', `DataLinker`の状態 |

### `experiment_stimuli` テーブル (NEW)

実験の**「設計（Plan）」**を管理します。実験で使用される可能性のある全ての刺激アセット（画像等）を事前に定義します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `stimulus_id` | BIGSERIAL | **PK**, 刺激のシステム内ユニークID |
| `experiment_id` | UUID | NOT NULL, _FK to experiments_ |
| `stimulus_name` | VARCHAR(255) | NOT NULL, イベントリストで使われる刺激名 (例: 'image_895.jpg') |
| `stimulus_type` | VARCHAR(50) | NOT NULL, 'image', 'audio'など |
| `trial_type` | VARCHAR(255) | 実験条件を示すラベル (例: 'target', 'nontarget') |
| `description` | TEXT | この個別の刺激に対する説明 |
| `object_id` | VARCHAR(512) | MinIOに保存された刺激ファイル本体への参照キー |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `session_events` テーブル (NEW)

セッションの**「実績（Log）」**を管理します。セッション中に実際に提示されたイベントのタイムスタンプ情報を記録します。
| カラム名 | 型 | 制約 / 説明 |
|:---|:---|:---|
| `event_id` | BIGSERIAL | **PK**, このイベントログの一意なID |
| `session_id` | VARCHAR(255) | NOT NULL, _FK to sessions_ |
| `stimulus_id` | BIGINT | _FK to experiment_stimuli_, どの定義済み刺激が使われたか（NULL許容） |
| `onset_s` | DOUBLE PRECISION | NOT NULL, セッション開始からのイベント発生時刻(秒) |
| `duration_s` | DOUBLE PRECISION | NOT NULL, イベントの継続時間(秒) |
| `trial_type`| VARCHAR(255) | このイベントインスタンスの実験条件 |
| `description` | TEXT | このイベントインスタンス固有の説明 |
| `value` | VARCHAR(255) | その他記録したい値 |

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

1.  **「計画」と「実績」の分離**:
    本システムの核となる思想は、**実験の「計画」(`experiment_stimuli`)**と、**セッションの「実績」(`session_events`)**を明確に分離することです。
    -   `experiment_stimuli`テーブルは、実験デザインフェーズで作成され、その実験で使われる全ての刺激アセットを定義します。これにより、データの完全性と再現性が保証されます。
    -   `session_events`テーブルは、実際のセッション中に何がいつ起きたかというタイムスタンプ情報（ログ）を記録します。
    -   この分離により、「All-in-Oneモード」と「Hybridモード（PsychoPy連携）」の両方のワークフローを単一のスキーマでエレガントに扱うことが可能になります。

2.  **メディアとセッションの非同期性**: `images`や`audio_clips`テーブルの`session_id`に外部キー制約を設けていない点は従来通りです。これにより、セッション中にキャプチャされる（刺激とは無関係な）メディアデータの非同期な投入を許容します。
