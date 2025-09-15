---
service_name: "Media Processor Service"
description: "スマートフォンアプリから送信されたメディアファイル（画像、音声）を永続化する専用サービス。"

inputs:
  - source: "Collector Service (via RabbitMQ: media_processing_queue)"
    data_format: "AMQP Message"
    schema: |
      Body: メディアファイル(バイナリ、アプリ側で圧縮されている可能性あり)
      Headers: {
        user_id,
        session_id,
        mimetype,
        original_filename,
        timestamp_utc,
        start_time_utc,
        end_time_utc
      }

outputs:
  - target: "MinIO"
    data_format: "Binary Data"
    schema: "メディア種別に応じたパスにファイル本体を格納"
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: "`images`テーブルまたは`audio_clips`テーブルへのメタデータ書き込み"
---

## 概要

`Media Processor`は、メディアファイル（画像、音声など）の永続化処理に特化したサービスです。メッセージキューからファイル本体と豊富なメタデータを受け取り、**`mimetype`に基づいて処理を分岐させ**、データ本体をオブジェクトストレージへ、メタデータを対応するデータベースのテーブルへ記録します。

## 詳細

- **責務**: **「メディアファイルを、その種類に応じた適切なメタデータと共に、永続的なストレージとデータベースに整理・保存すること」**。

- **処理フロー**:
    1. `media_processing_queue`からメッセージを一つ取り出す。
    2. メッセージヘッダーから`user_id`, `session_id`, `mimetype`, 各タイムスタンプなどの全てのメタデータを取得する。
    3. メッセージボディからメディアファイルのバイナリデータを取得する。
    4. `session_id`と`mimetype`、タイムスタンプから、MinIO に保存するための自己記述的なオブジェクト ID を生成する。
    5. データ本体を**MinIO にアップロードする**。
    6. **`mimetype`を元に処理を分岐する**:
      - `mimetype`が `'image/...'` で始まる場合:
        - `images`テーブルに、`object_id`, `user_id`, `session_id`, `timestamp_utc` などを`INSERT`する。
      - `mimetype`が `'audio/...'` で始まる場合:
        - `audio_clips`テーブルに、`object_id`, `user_id`, `session_id`, `start_time`, `end_time` などを`INSERT`する。

- **オブジェクト ID の命名規則 (例)**:
    - **目的**: パス自体がメタデータとして機能し、効率的な検索とデバッグを可能にするため。
    - **形式**: `media/{user_id}/{session_id}/{timestamp_ms}_{media_type}.{ext}`
    - **例**: `media/user-abcdef/user-abcdef-1726000000000/1726000500000_photo.jpg`

- **背景**:
  - **責務の特化**: `mimetype`に基づいた分岐処理や、画像と音声で異なるタイムスタンプ（撮影時刻 vs 開始/終了時刻）の扱いなど、メディアデータに特化したビジネスロジックをこのサービスに集約します。
  - **セッション ID の先行登録**: スマートフォンアプリから直接`session_id`が付与されるため、`DataLinker`による後からの紐付け処理を待つことなく、メディアデータをセッションと関連付けて保存できます。これにより、システム全体のデータ整理のパイプラインが簡素化されます。`sessions`テーブルに該当レコードが存在する前でも登録できるよう、DB スキーマ側で工夫されています。
