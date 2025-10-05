---
service_name: "Media Processor Service"
description: "スマートフォンアプリから送信されたメディアファイル（画像、音声）を永続化する専用の非同期ワーカー。"

inputs:
  - source: "Collector Service (via RabbitMQ: media_processing_queue)"
    data_format: "AMQP Message"
    schema: |
      Body: Media file (binary)
      Headers: {
        "user_id": "string",
        "session_id": "string",
        "mimetype": "string",
        "original_filename": "string",
        "timestamp_utc": "ISO8601 string (for images)",
        "start_time_utc": "ISO8601 string (for audio)",
        "end_time_utc": "ISO8601 string (for audio)"
      }

outputs:
  - target: "MinIO"
    data_format: "Binary Data with Metadata"
    schema: "メディア種別に応じたパスにファイル本体を格納。MinIOオブジェクト自体にもContent-TypeやユーザーIDなどのメタデータが付与される。"
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: "`images`テーブルまたは`audio_clips`テーブルへのメタデータ書き込み。`ON CONFLICT (object_id) DO NOTHING`で重複を防止。"
---

## 概要

`Media Processor`は、メディアファイル（画像、音声など）の永続化処理に特化した非同期ワーカーサービスです。RabbitMQの`media_processing_queue`からファイル本体と豊富なメタデータを受け取り、`mimetype`に基づいて処理を分岐させ、データ本体をオブジェクトストレージ（MinIO）へ、メタデータを対応するデータベース（PostgreSQL）のテーブルへ記録します。

## 詳細

-   **責務**: **「メディアファイルを、その種類に応じた適切なメタデータと共に、永続的なストレージとデータベースに整理・保存すること」**。

### 処理フロー (Asynchronous Worker)

1.  **メッセージ受信**: `media_processing_queue`からメッセージを一つ取り出します。
2.  **ヘッダー検証**: メッセージヘッダーを`zod`スキーマで厳格に検証します。`collector`サービスと同様に、`mimetype`が画像なら`timestamp_utc`、音声なら`start_time_utc`と`end_time_utc`が必須です。検証に失敗したメッセージは破棄されます（リキューされません）。
3.  **オブジェクトID生成**: メタデータに基づき、MinIOに保存するための自己記述的なオブジェクトIDを以下の形式で生成します。
    -   **形式**: `media/{user_id}/{session_id}/{timestamp_ms}_{media_type}.{ext}`
    -   `timestamp_ms`: 画像の場合は`timestamp_utc`、音声の場合は`start_time_utc`がミリ秒に変換されて使用されます。
    -   `media_type`: `mimetype`が`image/...`なら`photo`、それ以外は`audio`となります。
4.  **MinIOへのアップロード**: メッセージボディのバイナリデータを、生成したオブジェクトIDでMinIOの`media_bucket`にアップロードします。その際、MinIOオブジェクトのメタデータとして`Content-Type`, `X-User-Id`, `X-Session-Id`なども保存します。
5.  **データベースへの記録**: `mimetype`に応じて、対応するテーブルにメタデータを`INSERT`します。主キー（`object_id`）の重複コンフリクトが発生した場合は、`DO NOTHING`句によりエラーを出さずに処理をスキップします。
    -   **画像 (`image/...`)**: `images`テーブルに`object_id`, `user_id`, `session_id`, `timestamp_utc`などを記録します。
    -   **音声 (`audio/...`)**: `audio_clips`テーブルに`object_id`, `user_id`, `session_id`, `start_time`, `end_time`などを記録します。
6.  **メッセージ確認**: 処理が成功するとメッセージを`ack`（確認応答）してキューから削除します。処理中にエラーが発生した場合は`nack`してリキューさせ、再処理を試みます。

### APIエンドポイント

本サービスは主に非同期ワーカーとして動作しますが、デバッグやクライアント開発に便利なユーティリティAPIも提供しています。

-   `POST /api/v1/preview-object-id`
    -   **目的**: 実際にファイルをアップロードすることなく、指定したメタデータから生成されるであろうMinIOの`object_id`を事前に確認できます。
    -   **リクエストボディ**: `media_processing_queue`のAMQPヘッダーと同じ構造のJSONオブジェクト。
    -   **レスポンス**: `{"object_id": "media/.../....jpg"}` のように、生成される`object_id`を返します。