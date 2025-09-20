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

1.  **データ紐付け (Data Linking)**:
    - ジョブで指定された`user_id`と時間範囲 (`session_start_utc`から`session_end_utc`) をキーとして、`raw_data_objects`テーブルを検索。
    - 発見した全てのデータオブジェクトとセッションの関係を、中間テーブル `session_object_links` に `INSERT` する。
2.  **タイムスタンプ正規化 (Timestamp Normalization)**:
    - スマートフォンのクロックで記録されたメディアデータ（`images`, `audio_clips`）のタイムスタンプを、クロックオフセット情報を用いて補正し、データベースの値を`UPDATE`する。
    - 同時に、メディアデータに属する`experiment_id`を`UPDATE`する。
  
* **Hybridモードにおける高度な責務**:
    * PsychoPyなど外部アプリと連携するHybridモードの場合、本サービスはさらに高度な責務を担います。
    * センサーデータには、スマートフォンとの時刻同期とは独立した、マイクロ秒精度のトリガ情報（刺激が提示された正確なタイミング）が含まれています。
    * `DataLinker`は、セッション終了後にアップロードされた実績イベントログ (`session_events`) のシーケンスと、センサーデータ内のトリガのシーケンスを照合します（シーケンスマッチング）。
    * この処理により、PCとスマホのクロックの僅かなズレに影響されることなく、各イベントの発生時刻 (`onset`) を、マイコンの高精度な内部時間に紐づけられた正確な値へと補正することが可能になります。これは、システムのデータ信頼性を担保する上で極めて重要な処理です。


### 処理フロー (Processing Flow)

1.  非同期タスクキューから紐付けジョブを一つ取り出す。
2.  `sessions`テーブルの該当セッションの`link_status`を`'processing'`に更新する。
3.  **データオブジェクトの検索**:
    - ジョブ内の`user_id`, `session_start_utc`, `session_end_utc`を基に、関連する`raw_data_objects`を PostgreSQL から`SELECT`する。
    - **注意**: オブジェクトがセッション境界をまたぐことを考慮し、検索範囲は `object.start_time < session.end_time AND object.end_time > session.start_time` のような条件で行う。
4.  **トランザクション開始**: `BEGIN;`
5.  **センサーデータの紐付け**:
    - 検索された`raw_data_objects`の各レコードに対し、`session_id`と`object_id`のペアを`session_object_links`テーブルに`INSERT`する。
6.  **メディアデータのタイムスタンプ正規化と紐付け**:
    - 検索された`images`と`audio_clips`の各レコードに対し、タイムスタンプを正規化し、`experiment_id`を付与する`UPDATE`文を実行する。
7.  `sessions`テーブルの`link_status`を`'completed'`に更新する。
8.  **トランザクション終了**: `COMMIT;`
9.  エラー発生時は`ROLLBACK`を実行し、`link_status`を`'failed'`に更新する。

### 背景 (Background)

- **非同期処理**: データオブジェクトの検索と紐付けは重い処理のため、API コールから分離し非同期に実行することで、アプリの応答性を保ちます。
- **`session_object_links`テーブルの必要性**:
  - 将来、通信効率向上のために複数のデータパケット（例: 10 秒分）を単一のオブジェクトとして MinIO に保存する可能性があります。その場合、オブジェクトの記録期間がセッションの開始・終了時点をまたぐケースが考えられます。
  - `session_object_links`中間テーブルは、このような**「単一のデータオブジェクトが、複数のセッションにまたがって属する」**という多対多の関連を表現するために不可欠です。これにより、データ永続化の単位と、意味的な区切りであるセッションを柔軟に管理できます。
