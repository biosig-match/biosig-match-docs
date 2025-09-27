---
service_name: "DataLinker Service"
description: "セッション終了後に起動する第一段階の非同期ワーカー。センサーデータのタイムスタンプをUTCに正規化し、全ての関連データをセッションに紐付ける。"

inputs:
  - source: "Session Manager Service (via RabbitMQ: data_linker_queue)"
    data_format: "Job Payload (JSON)"
    schema: |
      {
        "session_id": "user-abcdef-1726000000000",
        "user_id": "user-abcdef",
        "experiment_id": "uuid-for-experiment",
        "session_start_utc": "2025-09-15T10:00:00Z",
        "session_end_utc": "2025-09-15T10:30:00Z",
        "clock_offset_info": {
          "offset_ms_avg": -150.5,
          "rtt_ms_avg": 45.2
        }
      }
  - source: "PostgreSQL"
    data_format: "SQL SELECT/UPDATE"
    schema: "`raw_data_objects`, `images`, `audio_clips`, `sessions` テーブルの読み取りと更新"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL UPDATE/INSERT"
    schema: "`raw_data_objects`のUTC時刻更新、`session_object_links`への挿入、`images`/`audio_clips`の`experiment_id`更新、`sessions`の`link_status`更新"
  - target: "Async Task Queue (EventCorrector)"
    data_format: "Job Payload (JSON)"
    schema: |
      {
        "session_id": "user-abcdef-1726000000000"
      }
---

## 概要

`DataLinker`は、`Session Manager`から非同期タスクキュー経由でジョブを受け取り、バックグラウンドで実行されるワーカーサービスです。主な責務は、セッション終了直後の未整理なデータ群に対し、**「時刻の正規化」**と**「メタデータの紐付け」**という第一段階の整理処理を高速に実行し、後続のより専門的な処理（イベント時刻補正など）へデータを引き渡すことです。

## 詳細

### 責務 (Responsibilities)

1.  **センサーデータのタイムスタンプ正規化 (Sensor Data Timestamp Normalization)**:
    - `Processor`サービスによって記録されたデバイスの内部クロック値 (`start_time_device`, `end_time_device`) を、ジョブで渡される`clock_offset_info`を用いて正確なUTC時刻に変換し、同テーブルの`start_time`および`end_time`カラムを`UPDATE`します。この処理は生データファイル自体には一切触れず、メタデータのみを更新することでデータの完全性を保証します。

2.  **データ紐付け (Data Linking)**:
    - **センサーデータ**: 正規化されたUTCタイムスタンプを元に、セッション期間と重なる`raw_data_objects`を特定し、`session_object_links`テーブルに紐付けます。
    - **メディアデータ**: `images`および`audio_clips`テーブルのレコードを`session_id`で直接特定し、属する`experiment_id`を付与します。

3.  **後続処理のトリガー (Triggering Downstream Processing)**:
    - 上記の処理がすべて正常に完了した後、`EventCorrectorService`のために新しいジョブ（`session_id`のみを含む）を`event_correction_queue`に投入します。

### 処理フロー (Processing Flow)

1.  `data_linker_queue`から紐付けジョブを一つ取り出します。
2.  **データベーストランザクションを開始します (`BEGIN;`)**。
3.  `sessions`テーブルの該当セッションの`link_status`を`'processing'`に更新します。
4.  **センサーデータのタイムスタンプ正規化**:
    - ジョブペイロードに`clock_offset_info`が存在する場合、`user_id`をキーに、まだUTC時刻が設定されていない (`start_time IS NULL`) `raw_data_objects`レコードを検索します。
    - `clock_offset_info`を用いて各オブジェクトの`start_time`と`end_time`を計算し、`UPDATE`文を実行します。
5.  **センサーデータの紐付け**:
    - 正規化されたUTCタイムスタンプを元に、セッション期間 (`session_start_utc`, `session_end_utc`) と重なる`raw_data_objects`を特定し、`session_object_links`テーブルに`INSERT`します。
6.  **メディアデータの紐付け**:
    - `images`および`audio_clips`テーブルを`session_id`で直接検索し、`experiment_id`を付与する`UPDATE`文を実行します。
7.  `sessions`テーブルの`link_status`を`'completed'`に更新します。
8.  **後続ジョブの投入**:
    - `EventCorrectorService`のために、`session_id`を含む新しいメッセージを`event_correction_queue`に送信します。
9.  **トランザクションをコミットします (`COMMIT;`)**。
10. 処理中にエラーが発生した場合は`ROLLBACK`を実行し、`link_status`を`'failed'`に更新して、ジョブをリトライさせずに終了します（NACK）。

### 背景 (Background)

- **非同期処理**: データオブジェクトの検索と紐付けは、セッション終了APIの応答時間に影響を与えないよう、完全に非同期で実行されます。
- **データパイプラインの中継点**: `DataLinker`は、単純なデータ永続化（`Processor`）と、計算負荷の高い専門的な処理（`EventCorrector`, `BIDS Exporter`）とを繋ぐ、重要な中間処理の役割を担います。責務を限定することで、サービス全体の堅牢性と保守性を高めています。
- **`session_object_links`テーブルの必要性**: 複数のデータパケットを単一のオブジェクトとして保存する場合、オブジェクトの記録期間がセッションの境界をまたぐ可能性があります。`session_object_links`中間テーブルは、このような多対多の関連を表現するために不可欠です。
