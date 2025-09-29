---
service_name: "BIDS Exporter Service"
description: "B2B向けのERP解析の前処理として、指定された実験の完了済みセッションデータを収集し、BIDS形式に準拠したデータセットとしてパッケージングする、権限管理機能付きの非同期バッチ処理サービス。"

inputs:
  - source: "ERP Neuro-Marketing Service"
    data_format: "HTTP POST (JSON)"
    schema: "エンドポイント `/api/v1/export/bids`: { experiment_id, user_id }"
  - source: "Auth Manager Service"
    data_format: "HTTP GET (Internal API Call)"
    schema: "権限確認リクエスト: { user_id, experiment_id, required_role: 'owner' }"
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "指定された`experiment_id`に属する**完了済み**セッション、イベント、刺激定義のメタデータ"
  - source: "MinIO"
    data_format: "Object GET"
    schema: "セッションに対応する圧縮済み生データ（EEG/IMU）と、**実験刺激として登録されたメディアファイル**"

outputs:
  - target: "MinIO"
    data_format: "ZIP Archive"
    schema: "BIDS形式のディレクトリ構造を持つ圧縮済みデータセット"
  - target: "RabbitMQ (Queue: export_completion_queue)"
    data_format: "AMQP Message (JSON)"
    schema: |
      {
        "job_id": "unique-job-id-for-tracking",
        "experiment_id": "uuid-for-experiment",
        "status": "completed",
        "output_object_id": "bids_datasets/experiment-id_timestamp.zip"
      }
---

## 概要

`BIDS Exporter`は、`ERP Neuro-Marketing Service`からのオンデマンド要求によって起動される、専門的なデータパッケージングサービスです。その責務は、**ERP解析に必要なデータのみを厳選**し、標準化されたBIDS形式のデータセットを生成することに特化しています。

## 詳細

  - **責務**: **「権限を検証し、完了済みの実験データを抽出し、後段の解析サービスが直接利用可能なBIDS形式のアーカイブを生成すること」**。

  - **権限管理 (Authorization)**:

      - 本サービスは、リクエストを受け付けると、まず`user_id`と`experiment_id`を`Auth Manager Service`に渡し、リクエスト元ユーザーが対象実験の\*\*`owner`ロールを持っているか\*\*を厳密に検証します。権限がない場合は、即座に`403 Forbidden`エラーを返します。

  - **データ選別 (Data Filtering)**:

      - **セッション状態**: PostgreSQLに問い合わせる際、`sessions`テーブルのステータスが`'completed'`（またはそれに類する完了状態）のレコードのみを処理対象とします。実行中のセッションデータはエクスポートに含めません。
      - **画像・音声データ**: BIDSデータセットに含める刺激ファイルは、**`experiment_stimuli`テーブルで定義されたものに限定**します。セッション中に自動撮影されたユーザーシーン解釈用のメディアデータ（`images`, `audio_clips`テーブルで管理）は、ERP解析の文脈ではノイズとなるため、**完全に無視**します。

  - **処理フロー (Processing Flow)**:

    1.  `ERP Neuro-Marketing Service`から`experiment_id`と`user_id`を含むAPIリクエストを受信します。
    2.  `Auth Manager Service`に権限を問い合わせ、`owner`であることを確認します。
    3.  PostgreSQLから、`experiment_id`に紐づく**完了済み**の全セッション情報、`session_events`（実績ログ）、そして`experiment_stimuli`（刺激定義）を取得します。
    4.  MinIOから、関連する全ての圧縮済み生データオブジェクトと、`experiment_stimuli`で参照されている\*\*刺激ファイル（画像・音声）\*\*をダウンロードします。
    5.  生データを時系列に沿って結合し、Zstandardで解凍します。
    6.  MNE-Pythonライブラリなどを利用し、BIDSの規約に従ってディレクトリ構造を構築します。
          - `sub-{user_id}/ses-{session_id}/eeg/sub-{user_id}_ses-{session_id}_task-{session_type}_eeg.edf`
          - `sub-{user_id}/ses-{session_id}/eeg/sub-{user_id}_ses-{session_id}_task-{session_type}_events.tsv`
          - `stimuli/`ディレクトリに刺激ファイルを配置。
          - `participants.tsv`, `dataset_description.json`などを生成。
    7.  完成したBIDSディレクトリ全体を単一のZIPファイルに圧縮します。
    8.  生成したZIPファイルを、自己記述的な名前（例: `bids_datasets/{experiment_id}_{timestamp}.zip`）でMinIOにアップロードします。
    9.  処理の完了通知（成功ステータスとZIPファイルの`object_id`を含む）を`export_completion_queue`に送信し、後段の`ERP Neuro-Marketing Service`に処理の開始を伝えます。

-----
