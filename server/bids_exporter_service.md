---
service_name: "BIDS Exporter Service"
component_type: "service"
description: "完了済みセッションと刺激アセットを集約し、BIDS 形式データセットを生成して MinIO へ保存する FastAPI サービス。"
inputs:
  - source: "Session Manager Service / External dashboard"
    data_format: "HTTP POST"
    schema: |
      POST /api/v1/experiments/{experiment_id}/export
      Body: なし (header で X-User-Id を透過)
  - source: "ERP Neuro-Marketing Service"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /internal/v1/create-bids-for-analysis
      Body: { experiment_id: uuid }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: |
      - experiments, sessions (status: event_correction_status='completed')
      - session_events (onset_corrected_us 優先)
      - experiment_stimuli (stimulus_metadata)
      - raw_data_objects, images, audio_clips (MinIO オブジェクト参照)
  - source: "MinIO"
    data_format: "Object GET"
    schema: |
      - raw-data バケット: 生信号バイナリ (.bin)
      - media バケット: 刺激ファイル
outputs:
  - target: "MinIO (bids exports bucket)"
    data_format: "Object PUT (ZIP)"
    schema: |
      object_name: bids/{experiment_id}/task-{timestamp}.zip (configurable)
  - target: "Shared Volume"
    data_format: "ディレクトリ作成"
    schema: |
      output_dir = settings.export_output_dir / experiment_id
      (内部 API 用、ZIP 化しない)
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: |
      export_tasks(task_id, experiment_id, status, progress, result_file_path, error_message)
  - target: "HTTP クライアント"
    data_format: "JSON / ストリーム"
    schema: |
      - ExportResponse: {task_id,status,message,status_url}
      - TaskStatus: {task_id, experiment_id, status, progress, result_file_path?, error_message?}
      - ダウンロード: application/zip ストリーム
---

## 概要

BIDS Exporter は FastAPI + BackgroundTasks で実装されています。公開 API は非同期タスクを管理し、内部 API は同期的に BIDS データセットを生成して共有ボリュームに展開します。主要実装ファイルは次の通りです。

- `bids_exporter/src/app/server.py`: FastAPI ルーティング。
- `bids_exporter/src/domain/bids.py`: BIDS ディレクトリ生成ロジック。
- `bids_exporter/src/domain/tasks.py`: `export_tasks` テーブル操作。
- `bids_exporter/src/infrastructure/minio.py`: MinIO クライアント。

## サービスの役割と主なユースケース

- **研究者向けデータパッケージの自動生成**: セッション終了後に収集された原データ・イベントログを BIDS 規格へ再構成し、ZIP ファイルを MinIO に配置します。研究者はモバイルアプリまたは管理 UI からワンクリックでエクスポートを開始し、完了後のダウンロードリンクを取得できます。
- **解析パイプラインとの橋渡し**: ERP Neuro-Marketing サービスなど、下流の解析モジュールは内部 API (`/internal/v1/create-bids-for-analysis`) を呼ぶだけで最新のセッションを束ねた BIDS ツリーを生成できます。解析ジョブは共有ボリュームに直接アクセスする設計です。
- **タスク進捗の可視化**: `export_tasks` テーブルにステータス・進捗・結果ファイルのパスを永続化し、UI がポーリングすることで「キュー中」「生成中」「完了」「失敗」の状態を表示できます。失敗時のエラーメッセージも記録され、オペレーターが問題特定に利用します。
- **再実行の容易さ**: 既存タスクが失敗した場合でも、同じ実験 ID で新規タスクを起動すると最新セッションを再評価し、結果を別タスクとして保存します。過去タスクは履歴として残るため、成果物のバージョン管理にも利用できます。

## ランタイム構成

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 接続。 |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_USE_SSL` | MinIO 接続設定。 |
| `MINIO_RAW_DATA_BUCKET`, `MINIO_MEDIA_BUCKET`, `MINIO_BIDS_EXPORTS_BUCKET` | 読み書き先バケット。 |
| `EXPORT_OUTPUT_DIR` | 内部 API 用のローカル出力先 (デフォルト `/export_data`)。 |

## 公開 API

### `POST /api/v1/experiments/{experiment_id}/export`

| 項目 | 内容 |
| --- | --- |
| 入力 | URL パラメータ `experiment_id` (UUID)。ボディ無し。 |
| 動作 | `uuid4()` で `task_id` を発行し、`export_tasks` にレコード挿入。`BackgroundTasks` で `create_bids_dataset(zip_output=True)` を実行。 |
| レスポンス | `202 Accepted` + `ExportResponse`。`status_url` は `/api/v1/export-tasks/{task_id}`。 |

### `GET /api/v1/export-tasks/{task_id}`

`export_tasks` テーブルから状態を取得し、`TaskStatus` を返却。存在しない場合は 404。

### `GET /api/v1/export-tasks/{task_id}/download`

- `TaskStatus.status` が `completed` かつ `result_file_path` が設定されている必要がある。
- MinIO から `StreamingResponse` で ZIP を返却。`Content-Disposition` ヘッダーでファイル名を通知。

## 内部 API

### `POST /internal/v1/create-bids-for-analysis`

| 項目 | 内容 |
| --- | --- |
| 入力 | JSON: `{ experiment_id: UUID }`。 |
| 処理 | `create_bids_dataset(zip_output=False)` を同期実行。出力先パスを含む `InternalBidsResponse` を返却。 |
| エラー | 実験やセッション不足 → 404 (`ValueError` を 404 に変換)。その他は 500。 |

## BIDS 生成ロジック (ハイライト)

1. `sessions` から `event_correction_status='completed'` のセッションを取得。
2. `raw_data_objects` を時間順に結合し、EDF 出力のために連結。
3. `session_events.onset_corrected_us` を優先し、BIDS events.tsv の `onset` (秒) を計算。
4. 刺激ファイルを `stimuli/` ディレクトリへコピー。
5. ZIP 出力モードでは生成物を一時ディレクトリに展開後、MinIO の `MINIO_BIDS_EXPORTS_BUCKET` にアップロード、`export_tasks.result_file_path` を更新。

## ヘルスチェック

`GET /health` は MinIO 接続を試行し、失敗時は 503 を返却。

## 参考ファイル

- API スキーマ: `bids_exporter/src/app/schemas.py`
- タスク管理: `bids_exporter/src/domain/tasks.py`
- BIDS 処理: `bids_exporter/src/domain/bids.py`
