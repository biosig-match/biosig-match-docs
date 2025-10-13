---
service_name: "PostgreSQL Database"
component_type: "database"
description: "実験・セッション・刺激・解析結果など構造化メタデータを保持する永続ストア。全サービスの一貫性を担保する。"
inputs:
  - source: "Session Manager Service"
    data_format: "SQL INSERT/UPDATE/SELECT"
    schema: |
      - experiments, experiment_participants
      - sessions, session_events, experiment_stimuli, calibration_items
  - source: "Processor Service"
    data_format: "SQL INSERT"
    schema: |
      raw_data_objects(object_id, user_id, device_id, session_id?, start_time?, end_time?, timestamp_start_ms, timestamp_end_ms, sampling_rate, lsb_to_volts)
  - source: "Media Processor Service"
    data_format: "SQL INSERT"
    schema: |
      images(object_id, user_id, session_id, timestamp_utc)
      audio_clips(object_id, user_id, session_id, start_time, end_time)
  - source: "DataLinker Service"
    data_format: "SQL UPDATE/INSERT"
    schema: |
      sessions.link_status, raw_data_objects.start_time/end_time/session_id,
      session_object_links, images.experiment_id, audio_clips.experiment_id
  - source: "Event Corrector Service"
    data_format: "SQL UPDATE"
    schema: |
      session_events.onset_corrected_us,
      sessions.event_correction_status
  - source: "BIDS Exporter / ERP Neuro-Marketing"
    data_format: "SQL SELECT/INSERT"
    schema: |
      - export_tasks
      - erp_analysis_results (将来的な利用)
outputs:
  - target: "全アプリケーション"
    data_format: "SQL SELECT"
    schema: |
      各種読み取りクエリ (実験一覧、刺激メタデータ、解析対象など)
---

## 概要

`db/init.sql` に定義されたスキーマは idempotent で、UUID 拡張 (`uuid-ossp`) を利用します。以下は主要テーブルの仕様とサービス間の依存関係です。

### experiments

| 列 | 型 | 制約 |
| --- | --- | --- |
| `experiment_id` | UUID | PK, `uuid_generate_v4()` 既定 |
| `name` | VARCHAR(255) | NOT NULL |
| `description` | TEXT | 任意 |
| `password_hash` | VARCHAR(255) | 任意 (Bcrypt/Bun hash) |
| `presentation_order` | VARCHAR(50) | `sequential` or `random` |

**利用サービス**: Session Manager (作成・参照), Auth Manager (参照), DataLinker (参照), BIDS Exporter / ERP (参照)。

### experiment_participants

| 列 | 型 | 制約 |
| --- | --- | --- |
| `experiment_id` | UUID | PK, FK → experiments |
| `user_id` | VARCHAR(255) | PK |
| `role` | VARCHAR(50) | CHECK IN ('owner','participant') |
| `joined_at` | TIMESTAMPTZ | DEFAULT NOW() |

**利用サービス**: Auth Manager, Session Manager。

### sessions

| 列 | 型 | 制約 |
| --- | --- | --- |
| `session_id` | VARCHAR(255) | PK |
| `user_id` | VARCHAR(255) | NOT NULL |
| `experiment_id` | UUID | FK → experiments |
| `device_id` | VARCHAR(255) | 任意 |
| `start_time` | TIMESTAMPTZ | NOT NULL |
| `end_time` | TIMESTAMPTZ | 任意 |
| `session_type` | VARCHAR(50) | 任意 (calibration/main 等) |
| `link_status` | VARCHAR(50) | DEFAULT 'pending' |
| `event_correction_status` | VARCHAR(50) | DEFAULT 'pending' |

**利用サービス**: Session Manager (挿入/更新), DataLinker (status 更新), Event Corrector (status 更新), BIDS Exporter / ERP (対象フィルタ)。

### calibration_items

グローバル刺激のリスト。`object_id` に MinIO キーを保持。

### experiment_stimuli

| 列 | 型 | 制約 |
| --- | --- | --- |
| `stimulus_id` | BIGSERIAL | PK |
| `experiment_id` | UUID | FK → experiments |
| `file_name` | VARCHAR(255) | NOT NULL, UNIQUE (experiment_id, file_name) |
| `stimulus_type` | VARCHAR(50) | NOT NULL (`image`/`audio` 等) |
| `category`, `gender`, `item_name`, `brand_name`, `trial_type`, `description` | 任意 |
| `object_id` | VARCHAR(512) | MinIO キー |

**利用サービス**: Session Manager (参照), Stimulus Asset Processor (UPSERT), ERP (参照), BIDS Exporter (参照)。

### session_events

| 列 | 型 | 制約 |
| --- | --- | --- |
| `event_id` | BIGSERIAL | PK |
| `session_id` | VARCHAR(255) | FK → sessions |
| `stimulus_id` | BIGINT | FK → experiment_stimuli (NULL 可) |
| `calibration_item_id` | BIGINT | FK → calibration_items (NULL 可) |
| `onset` | DOUBLE PRECISION | NOT NULL |
| `duration` | DOUBLE PRECISION | NOT NULL |
| `trial_type`, `description`, `value` | 任意 |
| `onset_corrected_us` | BIGINT | NULL (Event Corrector が設定) |

**利用サービス**: Session Manager (再挿入), Event Corrector (更新), BIDS Exporter / ERP (参照)。

### raw_data_objects

| 列 | 型 | 制約 |
| --- | --- | --- |
| `object_id` | VARCHAR(512) | PK |
| `user_id` | VARCHAR(255) | NOT NULL |
| `device_id` | VARCHAR(255) | NOT NULL |
| `session_id` | VARCHAR(255) | FK → sessions (NULL 可) |
| `start_time` / `end_time` | TIMESTAMPTZ | NULL (DataLinker が補完) |
| `timestamp_start_ms` / `timestamp_end_ms` | BIGINT | NOT NULL |
| `sampling_rate` | DOUBLE PRECISION | NOT NULL |
| `lsb_to_volts` | DOUBLE PRECISION | NOT NULL |

**利用サービス**: Processor (挿入), DataLinker (更新), Event Corrector / BIDS / ERP (参照)。

### session_object_links

セッションと raw オブジェクトの多対多リンク。`DataLinker` が挿入。

### images / audio_clips

| 列 | 型 | 制約 |
| --- | --- | --- |
| `object_id` | VARCHAR(512) | PK |
| `user_id` | VARCHAR(255) | NOT NULL |
| `session_id` | VARCHAR(255) | 任意 |
| `experiment_id` | UUID | NULL → DataLinker が設定 |
| `timestamp_utc` | TIMESTAMPTZ | 画像のみ |
| `start_time`, `end_time` | TIMESTAMPTZ | 音声のみ |

### export_tasks

BIDS エクスポートタスク管理。`TaskStatus` API で利用。

### erp_analysis_results

ERP 解析結果保存用。現行実装では未使用だが、将来的な永続化に備えて定義済み。

## インデックス

`init.sql` ではクエリ頻度の高い列に複数のインデックス (`idx_sessions_experiment`, `idx_raw_data_objects_session_id` など) が追加されています。性能問題が顕在化した場合はここを起点に最適化します。

## 参考

- スキーマ: `db/init.sql`
- 接続ユーティリティ: 各サービスの `infrastructure/db.ts` / `.py`
