### ERP Neuro-Marketing Service

```markdown
service_name: "ERP Neuro-Marketing Service"
description: "B2B向けニューロマーケティングアプリケーションのバックエンド。指定された実験の脳波データを解析し、ERP（事象関連電位）に基づいてユーザーが関心を示した可能性のある商品を推奨する。"

inputs:
  - source: "Smartphone App or Web Dashboard"
    data_format: "HTTP POST (JSON)"
    schema: |
      - POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze
  - source: "Auth Manager Service"
    data_format: "HTTP GET (Internal API Call)"
    schema: "解析開始リクエスト時に、ユーザーが実験の所有者であるかどうかの権限を確認する。"
  - source: "BIDS Exporter Service"
    data_format: "HTTP POST (Internal API Call)"
    schema: "指定した実験のBIDSデータセット生成をリクエストし、生成先のパスを受け取る。"
  - source: "PostgreSQL Database"
    data_format: "SQL SELECT"
    schema: "実験に関連するセッション情報や刺激（商品）情報を取得する。"
  - source: "Shared Volume (e.g., MinIO)"
    data_format: "File System Read"
    schema: "BIDS Exporterによって生成されたBIDSデータセット（.eeg, .tsv, .jsonファイル群）を読み込む。"

outputs:
  - target: "Smartphone App or Web Dashboard"
    data_format: "HTTP Response (JSON)"
    schema: |
      {
        "recommendations": [
          {
            "file_name": "string",
            "item_name": "string (optional)",
            "brand_name": "string (optional)",
            "description": "string (optional)",
            "category": "string (optional)",
            "gender": "string (optional)"
          }
        ],
        "summary": "string"
      }
  - target: "Shared Volume (e.g., MinIO)"
    data_format: "File System Write"
    schema: "学習済みのERP検出モデル（.pklなど）を実験IDに紐づけて保存する。"
```

## 概要

本サービスは、B2B向けニューロマーケティング解析の頭脳として機能します。ユーザー（実験管理者）からのリクエストを受け、指定された実験の脳波データからERP（事象関連電位）を解析します。具体的には、キャリブレーションデータを用いて個人に最適化されたERP検出モデルを学習し、そのモデルを使って本番タスクデータから関心を示した刺激（商品）を特定します。最終的に、推奨商品リストと解析サマリーを生成し、クライアントに返却します。

## 詳細

- **責務**: **「指定された脳波データ実験に対し、ERP解析を実行し、ビジネス上の意思決定に利用可能な推奨商品リストを生成・提供すること」**。

- **API エンドポイント (API Endpoints)**:

    - `POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze`:
        - 指定された実験IDの解析ワークフロー全体を開始し、完了まで待機して結果を返す同期型のエンドポイント。
        - **リクエストボディは不要。**
        - 内部で権限検証、BIDSデータセットの準備、モデル学習、推論、結果生成までの一連の処理を実行する。
        - 成功すると、HTTP `200 OK` と共に `AnalysisResponse` スキーマに準拠したJSONレスポンスを返す。
        - 処理中にエラー（例: データ不足、外部サービス障害）が発生した場合は、適切なHTTPステータスコード（404, 500, 503など）と詳細メッセージを返す。

- **処理フロー (Processing Flow)**:

  1.  **解析リクエスト受付**: クライアント（アプリやダッシュボード）から `POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze` リクエストを受け付けます。
  2.  **権限検証**: リクエストヘッダーの認証情報に基づき、`Auth Manager` サービスに問い合わせ、ユーザーが指定された `experiment_id` の所有者（`owner`）であることを確認します。権限がない場合は `403 Forbidden` を返します。
  3.  **メタデータ取得**: PostgreSQLデータベースに接続し、指定された実験IDに紐づくセッション情報（キャリブレーション、本番タスク）および、刺激（商品）のメタデータを取得します。必要なセッションデータ（特に `event_correction_status = 'completed'` のもの）が存在しない場合は `404 Not Found` を返します。
  4.  **BIDSデータセット生成依頼**: `BIDS Exporter` サービスに対し、内部APIコールでBIDSデータセットの生成を依頼します。`BIDS Exporter` は、データベースから波形データを取得し、標準化されたBIDS形式で共有ボリューム上に展開後、そのルートパスを返します。
  5.  **Epochs生成**: BIDSデータセットのパスを元に、キャリブレーションデータと本番タスクデータの両方から、MNE-Pythonの`Epochs`オブジェクト（解析単位となる切り出された波形データ）を生成します。
  6.  **ERPモデル学習**: キャリブレーションデータから生成した`Epochs`を用いて、`ErpDetector`モデル（分類器）を学習します。学習済みのモデルは、後で再利用できるよう共有ボリューム上の `models/{experiment_id}/` ディレクトリに保存されます。
  7.  **推論実行**: 学習済みモデルを使い、本番タスクデータから生成した`Epochs`に対して推論を実行します。これにより、各刺激（商品）提示時に関心（ターゲット）を誘発したかどうかを判定します。
  8.  **結果集計**: 推論結果に基づき、関心（ターゲット）と判定されたイベントに対応する刺激（商品）の情報を集計し、推奨商品リスト (`recommendations`) を作成します。
  9.  **サマリー生成**: 解析結果の概要を示す簡単なサマリー文字列 (`summary`) を生成します。
  10. **レスポンス返却**: 生成した推奨商品リストとサマリーを `AnalysisResponse` スキーマのJSON形式でクライアントに返却します。