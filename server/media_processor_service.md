---
service_name: "Media Processor Service"
description: "スマートフォンアプリから送信されたメディアファイル（画像、音声）を永続化する専用サービス。"

inputs:
  - source: "Collector Service"
    data_format: "Media File (JPEG, WAV, etc.) with Metadata"
    schema: "Body: Binary Data, Headers/Message Attributes: { user_id, session_id }"

outputs:
  - target: "MinIO"
    data_format: "Binary Data (JPEG, WAV, etc.)"
    schema: "メディア種別ごとに分離されたファイル"
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: "`images`テーブル, `audio_clips`テーブルへのメタデータ書き込み"
---

## 概要

`Media Processor`は、`Processor Service`とは完全に独立して、メディアファイル（画像、音声など）の永続化処理に特化します。主な責務は、**データ本体のオブジェクトストレージへの格納と、そのメタデータのデータベースへの記録**です。生体センサーデータとは別のフローで処理することで、`raw_data_objects`テーブルへの書き込みロックを回避し、システム全体のパフォーマンスと安定性を向上させます。

## 詳細

- **責務**: **「メディアファイルを、後から検索・利用しやすい形で整理し、データ本体とメタデータをそれぞれ最適な場所に永続化すること」**。データの解凍や解析は行いません。

- **処理フロー**:

  1. `Collector`からメディア処理専用のキュー（例: RabbitMQ の`media_processing_queue`）経由でメッセージを受け取る。
  2. メッセージから`user_id`、`session_id`などのメタデータと、メディアデータの本体を取得する。
  3. 自己記述的な命名規則を持つオブジェクト ID を決定する。
  4. 決定したオブジェクト ID で、メディアデータ本体を **MinIO にアップロードする**。
  5. アップロード成功後、**オブジェクト ID、`user_id`、`session_id`、タイムスタンプなどのメタデータを、メディア種別に応じた PostgreSQL の専用テーブル（`images`または`audio_clips`）に INSERT する**。

- **オブジェクト ID の命名規則**:

  - **目的**: パス自体がメタデータとして機能し、効率的な検索を可能にするため。
  - **形式**: `media/{user_id}/{session_id}/{timestamp_ms}_{media_type}.{ext}`
  - **例**: `media/user-abcdef/user-abcdef-1726000000000/1726000500000_photo.jpg`

- **背景**: 生体センサーデータは非常に高頻度で`raw_data_objects`テーブルに書き込まれます。画像や音声のような比較的低頻度だがサイズの大きいファイルの永続化処理が同じテーブルやトランザクションを共有すると、ロック競合の原因となり、データ欠損のリスクを高めます。処理系統を完全に分離することで、互いの負荷から影響を受けない堅牢なシステムを実現します。
