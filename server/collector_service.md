---
service_name: "Collector Service"
description: "全生データの受信を一手に引き受ける、スケーラブルなAPIゲートウェイ。"
inputs:
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST (JSON)"
    schema: "{ user_id, payload_base64 }"
  - source: "スマートフォンアプリ"
    data_format: "画像/音声ファイル"
    schema: "JPEG, WAVなど"
  - source: "スマートフォンアプリ"
    data_format: "HTTP POST"
    schema: "時刻同期オフセット情報、メディアファイル"
outputs:
  - target: "RabbitMQ (Fanout Exchange: raw_data_exchange)"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
---

## 概要

`Collector`は、スマートフォンアプリから送信される全ての生データ（EEG/IMU，画像/音声ファイル）を受け付ける唯一の窓口です。受け取ったデータに対して一切の処理を行わず、メタデータ（`user_id`）をヘッダーに付与し、圧縮データ本体をメッセージボディとして RabbitMQ の Exchange に即座に発行（Publish）します。

## 詳細

- **責務**: **「データの受信と、メッセージブローカーへの迅速な転送」**。これ以外のロジック（データ解析、DB 保存、認証など）は持ちません。
- **背景**: このサービスを極限までシンプルに保つことで、大量の書き込みリクエストを高速に捌き、システム全体の可用性を高めます。処理が軽量であるため水平スケールが容易であり、システム全体のボトルネックになることを防ぎます。後段のサービスは RabbitMQ を介して非同期にデータを処理できるため、`Collector`がリクエストを待たせる時間も最小限に抑えられます。
- **処理フロー**:
  1.  `/api/v1/data` エンドポイントで HTTP POST リクエストを受け付ける。
  2.  JSON ボディから`user_id`と`payload_base64`を抽出する。
  3.  `payload_base64`をデコードして元の圧縮バイナリデータに戻す。
  4.  RabbitMQ の`raw_data_exchange`に対し、バイナリデータをボディ、`user_id`をヘッダーとしてメッセージを発行する。
  5.  スマートフォンアプリに `202 Accepted` レスポンスを即座に返す。
