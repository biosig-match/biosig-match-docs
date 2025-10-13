---
service_name: "MinIO"
component_type: "storage"
description: "EEG 生データ・刺激アセット・メディア・BIDS エクスポートを保存するオブジェクトストレージ層。"
inputs:
  - source: "Processor Service"
    data_format: "Object PUT"
    schema: |
      Bucket: raw-data
      Key: raw/{user_id}/{device_id}/start_ms={timestamp_start_ms}/end_ms={timestamp_end_ms}_{uuid}.bin
      Metadata:
        X-User-Id, X-Device-Id, X-Sampling-Rate, X-Lsb-To-Volts, X-Session-Id?
  - source: "Media Processor Service"
    data_format: "Object PUT"
    schema: |
      Bucket: media
      Key: media/{user_id}/{session_id}/{timestampMs}_{photo|audio}{ext}
      Metadata: X-User-Id, X-Session-Id, X-Original-Filename
  - source: "Stimulus Asset Processor Service"
    data_format: "Object PUT"
    schema: |
      Bucket: media
      Key: stimuli/{experiment_id}/{file_name}
      Metadata: Content-Type from MIME
  - source: "BIDS Exporter Service"
    data_format: "Object PUT"
    schema: |
      Bucket: bids-exports (設定値)
      Key: bids/{experiment_id}/{timestamp}.zip
outputs:
  - target: "Session Manager Service"
    data_format: "Object GET"
    schema: |
      - キャリブレーション刺激: calibration_items.object_id
      - 実験刺激: experiment_stimuli.object_id
  - target: "Event Corrector Service"
    data_format: "Object GET"
    schema: |
      raw-data バケットの .bin をダウンロードしてトリガ解析
  - target: "BIDS Exporter / ERP Neuro-Marketing"
    data_format: "Object GET"
    schema: |
      - 生データ / メディアを取得して BIDS を構築
      - 生成済み ZIP をダウンロード (公開 API)
---

## 概要

MinIO は S3 互換オブジェクトストレージで、3 つの主要バケットを運用します。

| バケット | 用途 | 代表的なキー |
| --- | --- | --- |
| `raw-data` | Processor が保存するセンサーデータ (.bin)。 | `raw/<user>/<device>/start_ms=.../end_ms=..._{uuid}.bin` |
| `media` | 刺激ファイル / 画像 / 音声。 | `stimuli/<experiment_id>/<file>`, `media/<user>/<session>/<timestamp>_photo.jpg` |
| `bids-exports` | BIDS Exporter が生成した ZIP。 | `bids/<experiment_id>/<timestamp>.zip` |

## オブジェクト構造

### raw データ (`.bin`)

- 先頭ヘッダは payload version 4。`Realtime Analyzer` と `Event Corrector` がこのフォーマットを使用。
- メタデータとして `X-Sampling-Rate`, `X-Lsb-To-Volts`, `X-Session-Id` (任意) を付与。

### 刺激アセット

- Stimulus Asset Processor が CSV 定義と整合するファイルを `stimuli/{experiment_id}/` に保存。
- `experiment_stimuli.object_id` にキーが格納され、`Session Manager` がダウンロード時に参照。

### 画像・音声

- Collector → Media Processor 経由で `media/{user}/{session}/` 配下に保存。
- `images` / `audio_clips` テーブルに `object_id` が記録され、`DataLinker` が `experiment_id` を補完。

### BIDS ZIP

- `create_bids_dataset(zip_output=True)` 実行時に `bids-exports` バケットへアップロード。
- `export_tasks.result_file_path` にオブジェクト名が保存され、ダウンロード API がストリーミング。

## セキュリティと設定

- 全サービスは環境変数 `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_USE_SSL` を共有。
- バケット初期化は各サービスの起動時 (`ensureMinioBucket`) で自動作成されます。

## 参考ファイル

- Processor: `processor/src/app/server.ts`
- Media Processor: `media_processor/src/app/server.ts`
- Stimulus Asset Processor: `stimulus_asset_processor/src/domain/services/processor.ts`
- BIDS Exporter: `bids_exporter/src/infrastructure/minio.py`
