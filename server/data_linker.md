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
        "clock_offset_info": {
          "offset_ms": 150,
          "calculated_at_utc": "2025-09-15T09:59:50Z"
        }
      }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "`raw_data_objects`, `images`, `audio_clips` テーブルから、指定された`user_id`と時間範囲に合致するレコードを検索"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL UPDATE"
    schema: "検索されたレコードの`session_id`, `experiment_id`カラムを更新。`images`, `audio_clips`テーブルのタイムスタンプカラムも正規化後の値で更新する。"
---

## 概要

`DataLinker`は、`Session Manager`から非同期タスクキュー（例: RabbitMQ, Celery など）経由でジョブを受け取り、バックグラウンドで実行されるワーカーサービスです。主な責務は、セッションの時間範囲内に記録された膨大なデータオブジェクト群（脳波、画像、音声）に対して、それがどの実験のどのセッションに属するかの情報を与えることです。

さらに、**スマートフォンとファームウェア間のクロックのズレを補正し、全てのセッション内データのタイムスタンプを単一の信頼できるタイムラインに正規化する**という重要な役割も担います。

## 詳細

### 責務 (Responsibilities)

1.  **データ紐付け (Data Linking)**:

    - ジョブで指定された`user_id`と時間範囲 (`session_start_utc`から`session_end_utc`) をキーとして、`raw_data_objects`, `images`, `audio_clips`テーブルを検索。
    - 発見した全てのレコードに対し、対応する`session_id`と`experiment_id`を UPDATE 文で書き込む。

2.  **タイムスタンプ正規化 (Timestamp Normalization)**:
    - **基準**: `Processor`サービスによってサーバー時刻(UTC)に補正済みの**脳波データ(`raw_data_objects`)のタイムスタンプを正**とする。
    - **対象**: スマートフォンの OS クロックに基づいて記録されたメディアデータ（`images`, `audio_clips`）のタイムスタンプ。
    - **補正ロジック**: ジョブで受け取ったクロックオフセット情報 (`clock_offset_info.offset_ms`) を用いて、メディアデータのタイムスタンプを脳波データのタイムラインに合わせる補正計算を行い、データベースの値を更新する。
      - `offset_ms`は `(phone_timestamp - firmware_timestamp)` として計算されていることを前提とする。
      - したがって、補正式は `corrected_media_timestamp = original_media_timestamp - offset_ms` となる。
    - この処理により、同一セッション内の全てのデータ（脳波、画像、音声）が、後段の解析（BIDS エクスポートなど）で利用可能な、一貫したタイムラインを共有するようになります。

### 処理フロー (Processing Flow)

1.  非同期タスクキューから紐付けジョブを一つ取り出す。
2.  `sessions`テーブルの該当セッションの`link_status`を`'processing'`に更新する。
3.  **データオブジェクトの検索**:
    - ジョブ内の`user_id`, `session_start_utc`, `session_end_utc`を基に、関連するデータオブジェクトを PostgreSQL から`SELECT`する。
    - **注意**: ネットワーク遅延などを考慮し、検索範囲はセッションの前後数秒間のバッファを持たせることが望ましい（例: `start_time - 5s` から `end_time + 5s`）。
4.  **トランザクション開始**:
    - `BEGIN;`
5.  **脳波データの紐付け**:
    - 検索された`raw_data_objects`のレコードに対し、`session_id`と`experiment_id`を付与する`UPDATE`文を実行する。
6.  **メディアデータのタイムスタンプ正規化と紐付け**:
    - 検索された`images`と`audio_clips`の各レコードに対してループ処理を行う。
    - `original_timestamp - clock_offset_info.offset_ms` を計算し、正規化されたタイムスタンプを求める。
    - `session_id`, `experiment_id`、そして**正規化後のタイムスタンプ**でレコードを`UPDATE`する。
7.  `sessions`テーブルの`link_status`を`'completed'`に更新する。
8.  **トランザクション終了**:
    - `COMMIT;`
9.  もし処理中に何らかのエラーが発生した場合は、`ROLLBACK`を実行し、`link_status`を`'failed'`に更新して、エラーをログに記録する。

### 背景 (Background)

セッション中に生成されるデータオブジェクトは数万から数百万に達する可能性があり、これらのレコード全てを検索し更新する処理は非常に時間がかかります。この重い処理を、`Session Manager`の API コール（セッション終了通知）から完全に分離し、非同期のバックグラウンドジョブとして実行することで、以下のメリットが生まれます。

- **API の応答性向上**: ユーザー（スマホアプリ）は、重い処理の完了を待つことなく、即座に応答を受け取れる。
- **耐障害性**: 紐付け処理中に万が一ワーカーがダウンしても、タスクキューの仕組みによりジョブは失われず、ワーカーの再起動後に処理を再試行できる。
- **関心の分離**: セッションのライフサイクル管理という責務と、データクレンジング・正規化という複雑なビジネスロジックを明確に分離できる。
