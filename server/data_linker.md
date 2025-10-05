---
service_name: "DataLinker Service"
description: "セッション終了後に起動する第一段階の非同期ワーカー。センサーデータのタイムスタンプをUTCに正規化し、全ての関連データをセッションに紐付ける。"

inputs:
  - source: "Session Manager Service (via RabbitMQ: data_linker_queue)"
    data_format: "Job Payload (JSON)"
    schema: |
      {
        "session_id": "uuid-v4-string"
      }
      // Note: The service primarily uses the session_id and fetches all other required data,
      // including clock_offset_info, from the database.
  - source: "PostgreSQL"
    data_format: "SQL SELECT/UPDATE"
    schema: "`sessions`, `raw_data_objects`, `images`, `audio_clips` テーブルの読み取りと更新"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL UPDATE/INSERT (within a transaction)"
    schema: "`raw_data_objects`のUTC時刻更新、`session_object_links`への挿入、`images`/`audio_clips`の`experiment_id`更新、`sessions`の`link_status`更新"
  - target: "Event Corrector Service (via RabbitMQ: event_correction_queue)"
    data_format: "Job Payload (JSON)"
    schema: |
      {
        "session_id": "uuid-v4-string"
      }
---

## 概要

`DataLinker`は、`Session Manager`から非同期タスクキュー経由でジョブを受け取り、バックグラウンドで実行されるワーカーサービスです。主な責務は、セッション終了直後の未整理なデータ群に対し、**「時刻の正規化」**と**「メタデータの紐付け」**という第一段階の整理処理を高速に実行し、後続のより専門的な処理（イベント時刻補正など）へデータを引き渡すことです。

---

## スキーマ変更に伴う抜本的な修正要件

新しいデータスキーマと、それに伴う`Processor`サービスの修正により、`DataLinker`サービスの責務は根本的に変わります。**このサービスの最も複雑なロジックは不要になり、その存在意義自体を再検討する必要があります。**

### 1. タイムスタンプ正規化処理の完全な廃止

- **旧責務:** `clock_offset_info`とデバイスティック値を用いて、ラップアラウンドを考慮しながらUTC時刻を計算する。
- **新アーキテクチャ:** この処理は**完全に不要**になります。`Processor`サービスが、AMQPヘッダーからミリ秒単位のUTCタイムスタンプ (`timestamp_start_ms`, `timestamp_end_ms`) を直接受け取り、`raw_data_objects`テーブルに書き込むため、`DataLinker`が時刻を計算する必要は一切ありません。

### 2. センサーデータ紐付け処理の廃止

- **旧責務:** 正規化したタイムスタンプを元に、セッション期間と重複する`raw_data_objects`を探し、`session_object_links`テーブルに記録する。
- **新アーキテクチャ:** この処理も**不要**になります。`Processor`サービスが`raw_data_objects`テーブルに直接`session_id`を保存するため、センサーデータとセッションの紐付けは既に完了しています。`session_object_links`テーブル自体が冗長になります。

### 3. 新しい（縮小された）責務

上記の変更により、`DataLinker`の責務は以下に限定されます。

1.  `data_linker_queue`から`session_id`を受け取る。
2.  `images`および`audio_clips`テーブルを`session_id`で検索し、`experiment_id`が`NULL`のレコードに`experiment_id`を設定する。
3.  `Event Corrector`サービスのために`event_correction_queue`へジョブを投入する。

### 4. アーキテクチャに関する提言

`DataLinker`の責務は、メディアファイルのメタデータ更新と、次のキューへのメッセージ投入のみに縮小されました。これは非常に軽量な処理です。

開発チームは、**この`DataLinker`サービスを廃止し、残った責務を他のサービスに統合すること**を強く推奨します。

- **統合案A:** `Session Manager`の`POST /api/v1/sessions/end`エンドポイントの処理に、このメディア紐付け処理と`Event Corrector`へのジョブ投入を追加する。
- **統合案B:** `Event Corrector`サービスの処理の冒頭で、このメディア紐付け処理を実行する。

これにより、サービスを一つ削減し、アーキテクチャ全体を簡素化できます。

**データベーススキーマに関する注意:**
`Processor`サービスの前提条件である`raw_data_objects`テーブルのスキーマ変更と同時に、不要になった`session_object_links`テーブルは削除すべきです。

```sql
-- このテーブルはProcessorサービスによるsession_idの直接記録により不要になる
DROP TABLE IF EXISTS session_object_links;
```

---

## 詳細

### 責務 (Responsibilities)

1.  **センサーデータのタイムスタンプ正規化 (Sensor Data Timestamp Normalization)**:
    -   `Processor`サービスによって記録されたデバイスの内部クロック値（32-bitマイクロ秒カウンタ）を、セッションに記録された`clock_offset_info`を用いて正確なUTC時刻に変換し、`raw_data_objects`テーブルの`start_time`および`end_time`カラムを更新します。

2.  **データ紐付け (Data Linking)**:
    -   **センサーデータ**: 正規化されたUTCタイムスタンプを元に、セッション期間と時間的に重なる`raw_data_objects`を特定し、`session_object_links`テーブルに紐付けます。
    -   **メディアデータ**: `images`および`audio_clips`テーブルのレコードを`session_id`で直接特定し、まだ`experiment_id`が設定されていないものに限り、属する`experiment_id`を付与します。

3.  **後続処理のトリガー (Triggering Downstream Processing)**:
    -   上記の処理がすべて正常に完了した後、`EventCorrectorService`のために新しいジョブを`event_correction_queue`に投入します。

### 処理フロー (Processing Flow)

処理はデータベースの単一トランザクション内で実行され、原子性が保証されます。

1.  **ジョブ受信**: `data_linker_queue`から`session_id`を含むジョブを一つ取り出します。
2.  **ステータス更新**: `sessions`テーブルの該当セッションの`link_status`を`'processing'`に更新します。
3.  **タイムスタンプ正規化 (`normalizeRawObjectTimestamps`)**: このステップは、デバイスの内部クロック（32-bit `us`カウンタ）をグローバルなUTC時刻に変換する本サービスの中核処理です。
    a.  セッションの`user_id`に紐づく`raw_data_objects`の中から、まだUTC時刻が設定されていない (`start_time IS NULL`) ものを候補として取得します。
    b.  セッションの`start_time`と`clock_offset_info.offset_ms_avg`から、セッション開始時点でのデバイスの期待時刻（64-bit `us`）を計算し、その下位32ビットを基準 (`deviceBase`) とします。
    c.  各候補オブジェクトの`start_time_device`（32-bit `us`）と基準との差分を、32-bit整数のラップアラウンドを考慮して計算します。これにより、セッション開始からの経過時間（マイクロ秒）が算出されます。
    d.  セッション開始UTC時刻にこの経過時間を加算することで、オブジェクトの正確なUTC開始・終了時刻を導出します。
    e.  算出されたUTC時刻を`raw_data_objects`テーブルの`start_time`および`end_time`カラムに`UPDATE`します。
4.  **センサーデータ紐付け (`linkRawObjectsToSession`)**:
    -   正規化されたUTCタイムスタンプを持つ`raw_data_objects`の中から、PostgreSQLの`TSTZRANGE`型と`&&`（重複）演算子を用いて、セッション期間 (`session.start_time`, `session.end_time`) と時間的に重なるものを特定します。
    -   特定されたオブジェクトとセッションの関連を`session_object_links`テーブルに`INSERT`します。`ON CONFLICT DO NOTHING`により、重複挿入は無視されます。
5.  **メディアデータ紐付け (`linkMediaToExperiment`)**:
    -   `images`および`audio_clips`テーブルを`session_id`で検索し、`experiment_id`が`NULL`のレコードに対して、セッションの`experiment_id`を`UPDATE`で設定します。
6.  **完了と後続ジョブ投入**:
    -   `sessions`テーブルの`link_status`を`'completed'`に更新します。
    -   `EventCorrectorService`のために、`session_id`を含む新しいメッセージを`event_correction_queue`に送信します。
7.  **トランザクション完了**: `COMMIT`を実行して全ての変更を確定します。処理中にエラーが発生した場合は`ROLLBACK`し、`link_status`を`'failed'`に更新します。