
### ERP Neuro-Marketing Service (新規)

```markdown
service_name: "ERP Neuro-Marketing Service"
description: "B2B向けニューロマーケティングアプリケーションのバックエンド。BIDSデータセットの解析をオーケストレーションし、ERP検出モデルの学習・推論を実行して、最終的な示唆（例：ユーザーが高く関心を示した商品リスト）を生成する。"

inputs:
  - source: "Smartphone App or Web Dashboard"
    data_format: "HTTP POST/GET (JSON)"
    schema: |
      - POST /api/v1/erp/experiments/{experiment_id}/analyze (解析開始)
      - GET /api/v1/erp/experiments/{experiment_id}/results (結果取得)
  - source: "BIDS Exporter Service (via RabbitMQ: export_completion_queue)"
    data_format: "AMQP Message (JSON)"
    schema: "BIDSエクスポートの完了通知"
  - source: "MinIO"
    data_format: "Object GET"
    schema: "BIDS Exporterが生成したZIPアーカイブ"
  - source: "Auth Manager Service"
    data_format: "HTTP GET (Internal API Call)"
    schema: "解析開始リクエスト時の権限確認"

outputs:
  - target: "BIDS Exporter Service"
    data_format: "HTTP POST (Internal API Call)"
    schema: "BIDSエクスポート処理のキック"
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`erp_analysis_results`テーブルへの解析結果の書き込み"
  - target: "Smartphone App or Web Dashboard"
    data_format: "HTTP Response (JSON)"
    schema: "解析ジョブの受付応答、および最終的な解析結果"
```

## 概要

本サービスは、提供いただいたPythonプログラム群（`ERPDetectorWrapper`など）のロジックを責務に持つ、B2B向けアプリケーションの頭脳です。ユーザー（実験管理者）からのリクエストを起点とし、`BIDS Exporter`によるデータ準備から、モデルの学習・推論、最終結果の保存まで、一連の解析ワークフロー全体を管理・実行します。

## 詳細

  - **責務**: **「B2B向けERP解析ワークフローの実行管理と、ビジネス上の意思決定に利用可能な、解釈済みの解析結果を生成・提供すること」**。

  - **API エンドポイント (API Endpoints)**:

      - `POST /api/v1/erp/experiments/{experiment_id}/analyze`:
          - 解析ワークフロー全体を開始するトリガー。
          - リクエスト元の権限を検証後、`BIDS Exporter`にジョブを依頼し、即座に`202 Accepted`とジョブIDを返す。実際の処理は非同期で進行する。
      - `GET /api/v1/erp/experiments/{experiment_id}/results`:
          - 指定された実験の最新の解析結果を取得する。処理が完了していなければ、ステータス（例: `processing`）を返す。

  - **処理フロー (Processing Flow)**:

    1.  **解析開始**: ユーザーがアプリやダッシュボードから解析開始をリクエスト。本サービスが`POST`リクエストを受け付けます。
    2.  **権限検証**: `Auth Manager`に問い合わせ、ユーザーが実験の`owner`であることを確認します。
    3.  **エクスポート依頼**: `BIDS Exporter`サービスの`/api/v1/export/bids`エンドポイントを内部的に呼び出し、データセットの生成を依頼します。
    4.  **ジョブ受付完了**: 依頼が成功したら、クライアントにジョブIDを含む`202 Accepted`を返し、HTTP接続を終了します。
    5.  **完了待機**: RabbitMQの`export_completion_queue`を監視し、`BIDS Exporter`からの完了通知を待ち受けます。
    6.  **解析実行**: 完了通知を受け取ったら、メッセージ内の`output_object_id`を元に、MinIOからBIDSデータセット（ZIP）をダウンロードし、一時領域に展開します。
    7.  **モデル学習**: BIDSデータセット内のキャリブレーションデータ（例: `task-calibration`）を読み込み、`ERPDetectorWrapper.train()`に相当する処理を実行して、ユーザー固有のERP検出モデルを学習します。
    8.  **推論実行**: 本タスクのデータ（例: `task-main`）を読み込み、学習済みモデルを用いて`ERPDetectorWrapper.inference()`に相当する処理を実行。各刺激（商品画像など）に対する関心スコアや「好み」の有無を判定します。
    9.  **結果集計**: 推論結果を集計し、最終的なアウトプット（例: 関心スコアが高い商品トップ10のリストとスコア）をJSON形式で生成します。
    10. **結果保存**: 生成した結果JSONを、`experiment_id`に紐づける形でPostgreSQLの`erp_analysis_results`テーブルに保存します。
