---
service_name: "Stimulus Asset Processor Service"
component_type: "service"
description: "Session Manager から渡された刺激アセット登録ジョブを処理し、CSV とファイル群を MinIO・PostgreSQL に反映する非同期ワーカー。"
inputs:
  - source: "RabbitMQ queue stimulus_asset_queue"
    data_format: "AMQP message (JSON)"
    schema: |
      {
        experiment_id: uuid,
        csvDefinition: [{ trial_type: string, file_name: string, description?: string }],
        files: [{ fileName: string, mimeType: string, contentBase64: string }]
      }
  - source: "HTTP クライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/jobs
      Body: StimulusAssetJobPayload (上記と同型)
outputs:
  - target: "MinIO (media bucket)"
    data_format: "Object PUT"
    schema: |
      Key: stimuli/{experiment_id}/{fileName}
      Metadata: Content-Type = mimeType
  - target: "PostgreSQL"
    data_format: "SQL UPSERT"
    schema: |
      INSERT INTO experiment_stimuli (
        experiment_id,
        file_name,
        stimulus_type,
        trial_type,
        description,
        object_id
      )
      ON CONFLICT (experiment_id, file_name)
      DO UPDATE SET stimulus_type, trial_type, description, object_id
  - target: "監視クライアント"
    data_format: "HTTP JSON"
    schema: |
      GET /api/v1/health -> { status, rabbitmq_connected, db_connected, minio_connected, queue, last_rabbit_connected_at?, timestamp }
      GET /health -> { status }
---

## 概要

Stimulus Asset Processor は Bun 製のコンシューマで、`session_manager` が投入するジョブを処理します。CSV とファイル内容は 1 メッセージに収められており、MinIO への保存と `experiment_stimuli` テーブルの更新を同一トランザクションで保証します (DB トランザクション + MinIO 書き込み)。実装は `stimulus_asset_processor/src/app/server.ts` および `stimulus_asset_processor/src/domain/services/processor.ts` に分割されています。

## サービスの役割と主なユースケース

- **刺激アセットの正規化**: モバイル/ウェブ UI からアップロードされた CSV と実ファイルを検証し、一貫したファイル名・MIME・trial_type を登録します。登録後は Session Manager や ERP サービスが同じ定義を参照できます。
- **トランザクション整合性の担保**: ファイル保存と DB 更新をワンショットで行い、いずれかが失敗した場合はロールバック。中途半端な状態を残さず、再キューでやり直せるようにします。
- **ストレージ命名規則の統一**: `stimuli/{experiment_id}/` 以下に格納することで、テナントごとにストレージを分けなくても衝突を避けられます。研究者はファイル名ベースで刺激を追跡できます。
- **運用・検証用 API**: `/api/v1/jobs` から手動でジョブを投げ込めるため、CSV 修正後の再投入やステージング環境での検証に利用できます。

## ランタイム構成

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 接続。 |
| `RABBITMQ_URL` | キュー接続。 |
| `STIMULUS_ASSET_QUEUE` | コンシューム対象キュー。 |
| `MINIO_*` | 刺激ファイル保存用バケット接続。 |

## ジョブ処理手順 (`handleMessage` → `processJob`)

1. メッセージを JSON として parse、`stimulusAssetJobPayloadSchema` (Zod) で検証。
2. トランザクション開始 (`BEGIN`)。
3. CSV 行を `Map(file_name → 定義)` に整形。
4. 各ファイル:
   - Base64 を decode。
   - `stimuli/{experiment_id}/{fileName}` に保存。
   - MIME から `stimulus_type` を推定 (`image`, `audio`, `other`)。
   - 対応する CSV 行を取り出し、`experiment_stimuli` に UPSERT。
5. コミット。失敗時は `ROLLBACK` して例外を投げ、コンシューマが `nack` 再キュー。

## HTTP エンドポイント

| メソッド | パス | 説明 |
| --- | --- | --- |
| `POST` | `/api/v1/jobs` | キューに直接ジョブを投入する管理用 API。RabbitMQ チャンネルが準備できていない場合は 503。 |
| `GET` | `/api/v1/health` | RabbitMQ / DB / MinIO の状態を返却。 |
| `GET` | `/health` | 簡易ヘルスチェック。 |

## 参考ファイル

- キュー制御: `stimulus_asset_processor/src/infrastructure/queue.ts`
- MinIO ラッパー: `stimulus_asset_processor/src/infrastructure/minio.ts`
- ドメインロジック: `stimulus_asset_processor/src/domain/services/processor.ts`
