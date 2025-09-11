---
service_name: "Collector Service"
description: "全生データ（センサー、画像、音声）の受信を一手に引き受ける、スケーラブルなAPIゲートウェイ。"

inputs:
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (JSON)"
    schema: "エンドポイント `/api/v1/data`: { user_id, payload_base64 }"
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (Multipart/form-data)"
    schema: "エンドポイント `/api/v1/media`: フォームパートにメディアファイルとメタデータ { user_id, session_id }"

outputs:
  - target: "RabbitMQ (Fanout Exchange: raw_data_exchange)"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
  - target: "RabbitMQ (Queue: media_processing_queue)"
    data_format: "AMQP Message"
    schema: "Body: メディアファイル, Headers: { user_id, session_id }"
---

## 概要

`Collector`は、スマートフォンアプリから送信される全てのデータを受け付ける唯一の窓口です。**データの種類に応じてエンドポイントを分け**、それぞれを対応するメッセージブローカーへ迅速に転送します。

- **センサーデータ (`/api/v1/data`)**: 受け取ったJSONから圧縮バイナリデータを抽出し、`raw_data_exchange`へ発行します。
- **メディアデータ (`/api/v1/media`)**: 受け取った画像・音声ファイルを、メタデータと共に`media_processing_queue`へ発行します。

## 詳細

- **責務**: **「データの種類に応じた受信と、適切な後段サービスへの迅速な転送」**。
- **背景**: 処理系統を入り口で分離することで、各サービスの独立性を高めます。センサーデータとメディアデータではペイロードのサイズや発生頻度が大きく異なるため、それぞれに最適化されたキューイング戦略をとることが可能になり、システム全体の安定性が向上します。