---
service_name: "Processor Service"
description: "生データを解凍・整形し、オブジェクトストレージとデータベースに永続化するバックエンドサービス。"
inputs:
  - source: "RabbitMQ (processing_queue)"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
outputs:
  - target: "MinIO"
    data_format: "Zstandard圧縮されたバイナリデータ"
    schema: "ファームウェアから送信されたペイロードそのもの"
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: "オブジェクトID、ユーザーID、タイムスタンプ等のメタデータ"
---

## 概要

`Processor`は、RabbitMQ から生データのメッセージを受け取り、永続化のための処理を行います。主な責務は、**受信した圧縮済みバイナリデータを一切変更せず、そのままオブジェクトストレージへ格納し、そのメタデータをデータベースへ記録する**ことです。

## 詳細

- **責務**: **「受信した生データを、変更不可能な（Immutable）一次情報として、信頼性の高いストレージに迅速に永続化すること」**。データの中身の解釈（解凍、分離など）には一切関与しません。

- **処理フロー**:
    1.  RabbitMQ の`processing_queue`からメッセージを一つ取り出す。
    2.   メッセージボディ（圧縮データ）から、後で検索キーとなる最小限のメタデータ（`device_id`やタイムスタンプ範囲）を**解凍せずに**読み取る。
    3.   自己記述的な命名規則を持つオブジェクト ID を決定する。
    4.   メッセージボディの**圧縮データをそのまま MinIO にアップロードする**。
    5.   アップロード成功後、**オブジェクト ID、`user_id`、データの開始・終了時刻などのメタデータを PostgreSQL の `raw_data_objects` テーブルに INSERT する**。

- **オブジェクト ID の命名規則**:
    - **形式**: `raw/{user_id}/start_ms={start_unix_ms}/end_ms={end_unix_ms}_{uuid}.zst`
    - **例**: `raw/user-abcdef/start_ms=1725986400000/end_ms=1725986400500_a1b2c3d4.zst`

- **背景**:
    - **データの完全性とトレーサビリティ**: 本システムの設計において、ファームウェアから送られてきたデータは「正」であり、サーバー側で変更すべきではないという思想に基づいています。`Processor`がデータの中身に関与しないことで、将来アルゴリズムのバグ等が発覚した際も、完全にオリジナルの状態でデータを再処理できることを保証します。
    - **責務の限定**: データの解凍や分離といった CPU 負荷の高い処理は、それを必要とする後段のサービス（`BIDS Exporter`や`Realtime Analyzer`）がそれぞれの責務として担います。`Processor`は永続化に特化することで、高いスループットと信頼性を維持します。
