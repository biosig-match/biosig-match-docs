---
service_name: "Processor Service"
description: "生データを解凍・整形し、オブジェクトストレージとデータベースに永続化するバックエンドサービス。"
inputs:
  - source: "RabbitMQ (processing_queue)"
    data_format: "AMQP Message"
    schema: "Body: バイナリデータ, Headers: { user_id }"
  - source: "RabbitMQ (processing_queue)"
    data_format: "AMQP Message"
    schema: "Body: JPEG, WAVなど, Headers: { user_id }"
  - source: "RabbitMQ (processing_queue)"
    data_format: "AMQP Message"
    schema: "Body: 時刻同期オフセット情報, Headers: { user_id }"
outputs:
  - target: "MinIO"
    data_format: "Zstandard圧縮されたバイナリデータ"
    schema: "EEG, IMUなどのデータ種別ごとに分離されたファイル"
  - target: "PostgreSQL"
    data_format: "SQL INSERT"
    schema: "オブジェクトID、ユーザーID、タイムスタンプ等のメタデータ"
---

## 概要

`Processor`は、RabbitMQ から生データのメッセージを受け取り、永続化のための処理を行います。主な責務は、データの解凍、タイムスタンプの補正、データ種別ごとの分離、そして**データ本体のオブジェクトストレージへの格納と、そのメタデータのデータベースへの記録**です。

## 詳細

- **責務**: **「生データを、後から検索・利用しやすい形で整理し、データ本体とメタデータをそれぞれ最適な場所に永続化すること」**。
- **処理フロー**:
  1.  RabbitMQ の`processing_queue`からメッセージを一つ取り出す。
  2.  メッセージボディ（圧縮データ）を Zstandard で解凍する。
  3.  解凍したデータから、`device_id`と各サンプルの内部タイムスタンプを読み取る。
  4.  （時刻同期）別途受信したオフセット情報に基づき、各サンプルの内部タイムスタンプをサーバー基準の UTC 時刻に補正する。
  5.  データを EEG、IMU などの種類ごとに分離する。
  6.  分離した各データを再度圧縮し、自己記述的な命名規則を持つオブジェクト ID を決定する。
  7.  決定したオブジェクト ID で、圧縮データを **MinIO にアップロードする**。
  8.  アップロード成功後、**オブジェクト ID、`user_id`、データの開始・終了時刻などのメタデータを PostgreSQL に INSERT する**。
- **オブジェクト ID の命名規則**: MinIO に保存する際のオブジェクト ID（ファイルパス）は、後からの検索性を最大限に高めるために、自己記述的な命名規則を採用します。
  - **形式**: `{data_type}/{user_id}/start_ms={start_unix_ms}/end_ms={end_unix_ms}_{uuid}.zst`
  - **例**: `eeg/user-abcdef/start_ms=1725986400000/end_ms=1725986400500_a1b2c3d4.zst`
- **背景**: バイナリデータのような巨大な非構造データを PostgreSQL に直接保存すると、データベースのパフォーマンスを著しく低下させます。データを専門のオブジェクトストレージに格納し、DB ではそのメタデータのみを管理する**「DB-Offloading パターン」**は、大規模データを扱うシステムの定石です。Processor がメタデータを即時記録することで、データの追跡可能性が向上し、システム全体の信頼性が高まります。
