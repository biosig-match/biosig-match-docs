---
service_name: "Stimulus Asset Processor Service"
description: "実験刺激アセット（画像、音声ファイル）の永続化を非同期で実行するバックエンドワーカーサービス。"

inputs:
  - source: "Session Manager Service (via RabbitMQ: stimulus_asset_queue)"
    data_format: "AMQP Message (JSON)"
    schema: |
      {
        "experiment_id": "uuid-for-experiment",
        "csvDefinition": [
          { "trial_type": "target", "file_name": "image1.jpg", "description": "Target A" },
          { "trial_type": "nontarget", "file_name": "image2.jpg", "description": "Distractor B" }
        ],
        "files": [
          { 
            "fileName": "image1.jpg", 
            "mimeType": "image/jpeg",
            "contentBase64": "..." 
          },
          { 
            "fileName": "image2.jpg",
            "mimeType": "image/jpeg",
            "contentBase64": "..." 
          }
        ]
      }

outputs:
  - target: "MinIO"
    data_format: "Binary Data"
    schema: "JPEG, WAVなどのメディアファイル本体"
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`experiment_stimuli`テーブルへのレコード書き込み"
---

## 概要

`Stimulus Asset Processor`は、`Session Manager`から非同期ジョブキュー（RabbitMQ）経由でジョブを受け取り、バックグラウンドで実行されるワーカーサービスです。主な責務は、実験の「計画」フェーズでアップロードされた全ての刺激アセット（画像や音声ファイル）を永続的なストレージ（MinIO）に保存し、そのメタデータをデータベース（PostgreSQL）に登録することです。

## 詳細

### 責務 (Responsibilities)

- **「非同期ジョブとして受け取った刺激アセット群のファイル本体とメタデータを、アトミックな操作として永続化すること」**に限定されます。

このサービスは、HTTPエンドポイントを持たず、メッセージキューのコンシューマとしてのみ動作します。

### 処理フロー (Processing Flow)

1.  `stimulus_asset_queue`からメッセージを一つ取り出す（デキュー）。
2.  メッセージボディのJSONをパースし、`experiment_id`、`csvDefinition`、`files`を取得する。
3.  **データベーストランザクションを開始**する (`BEGIN;`)。これにより、全てのアセットが登録されるか、全く登録されないかのどちらかであることが保証される（原子性）。
4.  ジョブペイロード内の`files`配列をループ処理する:
    1.  各ファイルの`contentBase64`をデコードし、バイナリデータ（Buffer）に戻す。
    2.  `experiment_id`と`fileName`から、MinIOに保存するためのオブジェクトIDを生成する（例: `stimuli/{experiment_id}/{fileName}`）。
    3.  バイナリデータを**MinIOにアップロード**する。
    4.  `csvDefinition`配列から、現在のファイルに対応する定義情報（`trial_type`や`description`）を見つけ出す。
    5.  `experiment_id`、ファイル名、定義情報、そしてMinIOから得られた`object_id`を`experiment_stimuli`テーブルに`INSERT`する。既存のレコードがある場合は`UPDATE`する（`ON CONFLICT`句を利用）。
5.  全てのファイルの処理が成功した場合、**トランザクションをコミット**する (`COMMIT;`)。
6.  処理中に何らかのエラー（MinIOへのアップロード失敗、DB書き込み失敗など）が発生した場合、**トランザクションをロールバック**し (`ROLLBACK;`)、処理の失敗をログに記録する。メッセージは再試行のためにキューに戻すか、デッドレターキューに送る。
7.  正常に処理が完了したら、メッセージキューにACK（確認応答）を返し、ジョブを完全に削除する。

### 背景 (Background)

-   **APIの応答性向上**: `Session Manager`が重いファイルI/O処理を直接行うと、多数のファイルを同時にアップロードした場合にAPIの応答が著しく遅延します。本サービスに処理を委譲することで、`Session Manager`はリクエストを即座に受け付け (`202 Accepted`)、ユーザー体験を損なうことなくバックグラウンドで処理を進めることができます。
-   **信頼性と一貫性**: データベースのトランザクション機能を利用することで、実験定義の原子性を保証します。「10個の画像のうち5個だけ登録されてしまった」といった中途半端な状態を防ぎ、データの整合性を高く保ちます。
-   **スケーラビリティ**: 将来的にアセット登録がシステムのボトルネックになった場合、APIサーバーである`Session Manager`とは独立して、本ワーカーサービスのインスタンス数のみを増やすことで、処理能力を柔軟にスケールさせることが可能です。
