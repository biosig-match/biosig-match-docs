---
service_name: "Stimulus Asset Processor Service"
description: "Session Managerから依頼を受け、実験で使用する刺激アセット（画像、音声など）を永続化する非同期ワーカーサービス。"

inputs:
  - source: "Session Manager Service (via RabbitMQ: stimulus_asset_queue)"
    data_format: "AMQP Message (JSON Job Payload)"
    schema: |
      {
        "experiment_id": "uuid-v4-string",
        "csvDefinition": [
          {
            "file_name": "string",
            "trial_type": "string",
            "description": "string | null"
          }
        ],
        "files": [
          {
            "fileName": "string",
            "mimeType": "string",
            "contentBase64": "string"
          }
        ]
      }

outputs:
  - target: "MinIO"
    data_format: "Binary Data"
    schema: "アップロードされたファイル本体。オブジェクトIDは `stimuli/{experiment_id}/{file_name}` の形式。"
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE (UPSERT)"
    schema: "`experiment_stimuli`テーブルへの刺激メタデータの書き込み。`ON CONFLICT (experiment_id, file_name)`句により、既存のレコードは更新される。"
---

## 概要

`Stimulus Asset Processor`は、`Session Manager`から刺激アセットの登録ジョブを受け取り、バックグラウンドで永続化処理を実行する、ヘッドレスな（APIエンドポイントを持たない）非同期ワーカーサービスです。主な責務は、アップロードされた各ファイルをオブジェクトストレージ（MinIO）に保存し、そのメタデータとCSVで定義された実験条件をデータベース（PostgreSQL）に記録することです。

## 詳細

-   **責務**: **「実験計画で定義された全ての刺激アセットを、アトミックな操作で永続化すること」**。
-   **アーキテクチャ**: 本サービスはRabbitMQの`stimulus_asset_queue`を監視するコンシューマとしてのみ機能します。ヘルスチェック以外のHTTP APIは提供しません。

### 処理フロー (Asynchronous Worker)

処理はデータベースの単一トランザクション内で実行され、全てのファイルとメタデータ登録の原子性が保証されます。

1.  **ジョブ受信**: `stimulus_asset_queue`からジョブメッセージを一つ取り出します。
2.  **ペイロード解析**: メッセージボディをJSONとしてパースし、`zod`スキーマでバリデーションします。
3.  **トランザクション開始**: PostgreSQLで`BEGIN`を実行します。
4.  **ファイル毎のループ処理**: ジョブペイロード内の`files`配列に含まれる各ファイルに対して、以下の処理を繰り返します。
    a.  **データデコード**: `contentBase64`文字列をデコードして、ファイルのバイナリデータを復元します。
    b.  **オブジェクトID生成**: `stimuli/{experiment_id}/{file.fileName}`という命名規則に従い、MinIOのオブジェクトIDを決定します。
    c.  **MinIOへアップロード**: 復元したバイナリデータを、生成したオブジェクトIDで`media_bucket`にアップロードします。
    d.  **DBへUPSERT**: `experiment_stimuli`テーブルに対し、`INSERT ... ON CONFLICT DO UPDATE`（UPSERT）を実行します。
        -   **キー**: `(experiment_id, file_name)`がコンフリクトの対象です。
        -   **INSERT**: 新規ファイルの場合、`experiment_id`, `file_name`, `object_id`、およびCSV定義から取得した`trial_type`, `description`などを挿入します。
        -   **UPDATE**: 既に同じ実験に同名のファイルが存在する場合、レコード全体を新しい情報（新しい`object_id`や`trial_type`など）で上書きします。これにより、刺激アセットの更新が容易になります。
5.  **トランザクション完了**: 全てのファイル処理が成功した場合、`COMMIT`を実行して変更を確定します。ループの途中で何らかのエラーが発生した場合は、`ROLLBACK`を実行して全ての変更を取り消し、ジョブをリキューさせて再処理を試みます。