---
service_name: "DataLinker Service"
description: "セッション終了後に起動し、記録された生データとセッション情報を紐付ける非同期バックエンドサービス。メディアデータのタイムスタンプ正規化も担う。"

inputs:
  - source: "Session Manager Service (via Async Task Queue)"
    data_format: "Job Payload (JSON)"
    schema: |
      {
        "session_id": "user-abcdef-1726000000000",
        "user_id": "user-abcdef",
        "experiment_id": "uuid-for-experiment",
        "session_start_utc": "2025-09-15T10:00:00Z",
        "session_end_utc": "2025-09-15T10:30:00Z",
        "clock_offset_info": { ... }
      }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "`raw_data_objects`, `images`, `audio_clips` テーブルから、指定された`user_id`と時間範囲に合致するレコードを検索"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`session_object_links`テーブルへのINSERT、`images`と`audio_clips`のタイムスタンプ正規化と`experiment_id`のUPDATE"
---

## 概要

`DataLinker`は、`Session Manager`から非同期タスクキュー経由でジョブを受け取り、バックグラウンドで実行されるワーカーサービスです。主な責務は、セッションの時間範囲内に記録された膨大なデータオブジェクト群（脳波、画像、音声）に対して、それがどの実験のどのセッションに属するかの情報を与えることです。

## 詳細

### 責務 (Responsibilities)
1.  **センサーデータのタイムスタンプ正規化 (Sensor Data Timestamp Normalization)**:
      - `Processor`サービスによって記録されたデバイスの内部クロック値 (`start_time_device`, `end_time_device`) を、ジョブで渡される`clock_offset_info`を用いて正確なUTC時刻に変換し、同テーブルの`start_time`および`end_time`カラムを`UPDATE`します。
2.  **データ紐付け (Data Linking)**:
      - 正規化されたUTCタイムスタンプを元に、セッション期間と重なる`raw_data_objects`を特定し、`session_object_links`テーブルに紐付けます。
      - `images`および`audio_clips`テーブルのレコードに、ジョブで指定された`experiment_id`を付与します。
3.  **生データの完全性の保証**
      - 脳波データなどの生データに対してタイムスタンプの補正を行ってしまうと、最悪の場合オブジェクト間でデータが不連続になるなど、ミリ秒単位の精度を必要とする脳波の実験に影響を与える可能性があります。
      - したがって、このサービスの責務を`start_time_device`, `end_time_device`といったメタデータの補正に限定することで、生データの完全性を維持します。

  
* **Hybridモードにおける高度な責務**:
    * PsychoPyなど外部アプリと連携するHybridモードの場合、本サービスはさらに高度な責務を担います。
    * センサーデータには、スマートフォンとの時刻同期とは独立した、マイクロ秒精度のトリガ情報（刺激が提示された正確なタイミング）が含まれています。
    * `DataLinker`は、セッション終了後にアップロードされた実績イベントログ (`session_events`) のシーケンスと、センサーデータ内のトリガのシーケンスを照合します（シーケンスマッチング）。
    * この処理により、PCとスマホのクロックの僅かなズレに影響されることなく、各イベントの発生時刻 (`onset`) を、マイコンの高精度な内部時間に紐づけられた正確な値へと補正することが可能になります。これは、システムのデータ信頼性を担保する上で極めて重要な処理です。


### 処理フロー (Processing Flow)

1.  非同期タスクキューから紐付けジョブを一つ取り出す。
2.  `sessions`テーブルの該当セッションの`link_status`を`'processing'`に更新する。
3.  **センサーデータの検索とタイムスタンプ正規化**:
      - ジョブ内の`user_id`をキーに、まだUTC時刻が設定されていない (`start_time IS NULL`) `raw_data_objects`レコードを検索します。
      - `clock_offset_info`を用いて各オブジェクトの`start_time`と`end_time`を計算し、`UPDATE`文を実行します。
4.  **トランザクション開始**: `BEGIN;`
5.  **センサーデータの紐付け**:
      - **正規化されたUTCタイムスタンプを元に**、セッション期間 (`session_start_utc`, `session_end_utc`) と重なる`raw_data_objects`を特定し、`session_object_links`テーブルに`INSERT`します。
6.  **メディアデータの紐付け**:
      - `images`および`audio_clips`テーブルを\*\*`session_id`で直接検索\*\*し、`experiment_id`を付与する`UPDATE`文を実行します。
7.  `sessions`テーブルの`link_status`を`'completed'`に更新する。
8.  **トランザクション終了**: `COMMIT;`
9.  エラー発生時は`ROLLBACK`を実行し、`link_status`を`'failed'`に更新する。

### 背景 (Background)

- **非同期処理**: データオブジェクトの検索と紐付けは重い処理のため、API コールから分離し非同期に実行することで、アプリの応答性を保ちます。
- **`session_object_links`テーブルの必要性**:
  - 将来、通信効率向上のために複数のデータパケット（例: 10 秒分）を単一のオブジェクトとして MinIO に保存する可能性があります。その場合、オブジェクトの記録期間がセッションの開始・終了時点をまたぐケースが考えられます。
  - `session_object_links`中間テーブルは、このような**「単一のデータオブジェクトが、複数のセッションにまたがって属する」**という多対多の関連を表現するために不可欠です。これにより、データ永続化の単位と、意味的な区切りであるセッションを柔軟に管理できます。
- DataLinker
