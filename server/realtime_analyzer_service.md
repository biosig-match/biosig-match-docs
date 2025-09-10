---
service_name: "Realtime Analyzer Service"
description: "生データをリアルタイムに解析し、結果をAPI経由で提供するサービス。"
inputs:
  - source: "RabbitMQ (analysis_queue)"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
outputs:
  - target: "スマートフォンアプリ"
    data_format: "HTTP GET (JSON)"
    schema: "{ psd_image_b64, coherence_image_b64, timestamp }"
---

## 概要

`Realtime Analyzer`は、`Processor`とは独立して RabbitMQ から生データを受け取ります。受け取ったデータをメモリ上のバッファに蓄積し、一定時間ごとに（例: 10 秒）直近のデータを用いて脳波解析（PSD、Coherence など）を実行します。解析結果は画像として生成され、ユーザー ID ごとに最新のものが保持されます。

## 詳細

- **責務**: **「準リアルタイムでのデータ解析と、その結果の即時提供」**。データの永続化には一切関与しません。
- **処理フロー**:
  1.  RabbitMQ の`analysis_queue`からメッセージを取り出す。
  2.  ヘッダーの`user_id`をキーとして、メモリ内のデータバッファを特定する。
  3.  メッセージボディを解凍し、データを該当ユーザーのバッファに追加する。
  4.  バックグラウンドで定期的に動作する解析ワーカーが、各ユーザーのバッファから直近 N 秒間のデータを取得する。
  5.  MNE-Python などのライブラリを用いて解析を行い、結果を Matplotlib でプロットし、Base64 エンコードされた画像文字列としてメモリに保存する。
- **API エンドポイント**: `GET /api/v1/users/{user_id}/analysis`
  - 認証ミドルウェアなどを介してリクエスト元のユーザー ID を特定し、そのユーザーに対応する最新の解析結果画像を JSON 形式で返します。
- **背景**: リアルタイム解析は、永続化処理とは要求される性能特性が全く異なります。DB 書き込みの遅延などに影響されず、常に最新のデータを低遅延で処理し続ける必要があるため、`Processor`から完全に分離された独立したサービスとして実装します。これにより、ユーザーはスムーズなフィードバックを受け取ることができ、システム全体の応答性が向上します。
