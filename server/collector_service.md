---
service_name: "Collector Service"
description: "全生データ（センサー、画像、音声）の受信を一手に引き受ける、スケーラブルな API ゲートウェイ。"

inputs:
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (JSON)"
    schema: "エンドポイント `/api/v1/data`: { user_id, payload_base64 }"
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (Multipart/form-data)"
    schema: |
      エンドポイント `/api/v1/media`: フォームパートにメディアファイルとメタデータを含む
      - file: (バイナリデータ)
      - user_id: (VARCHAR)
      - session_id: (VARCHAR)
      - mimetype: (VARCHAR) 例: 'image/jpeg', 'audio/m4a'
      - original_filename: (VARCHAR)
      - timestamp_utc: (ISO8601 String, 画像用)
      - start_time_utc: (ISO8601 String, 音声用)
      - end_time_utc: (ISO8601 String, 音声用)

outputs:
  - target: "RabbitMQ (Fanout Exchange: raw_data_exchange)"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
  - target: "RabbitMQ (Queue: media_processing_queue)"
    data_format: "AMQP Message"
    schema: |
      Body: メディアファイル(バイナリ)
      Headers: {
        user_id,
        session_id,
        mimetype,
        original_filename,
        timestamp_utc,
        start_time_utc,
        end_time_utc
      }
---

## 概要

`Collector`は、スマートフォンアプリから送信される全てのデータを受け付ける唯一の窓口です。データの種類に応じてエンドポイントを分け、それぞれを対応するメッセージブローカーへ迅速に転送します。

- **センサーデータ (`/api/v1/data`)**: 受け取った JSON から圧縮バイナリデータを抽出し、`raw_data_exchange`へ発行します。
- **メディアデータ (`/api/v1/media`)**: 受け取ったメディアファイルと、**付随する全てのメタデータをそのまま**メッセージヘッダーとして、`media_processing_queue`へ発行します。

## 詳細

- **責務**: **「データの種類に応じた受信と、ビジネスロジックを一切介さず、後段サービスへ迅速かつ透過的に転送すること」**。
- **背景**: 処理系統を入り口で分離することで、各サービスの独立性を高めます。特にメディアデータは、その種類を判別するためのロジックやタイムスタンプ解釈などを一切行わず、後段の`Media Processor`に責務を完全に委譲します。これにより、`Collector`は軽量なゲートウェイとしての役割に徹し、高いスループットを維持します。
