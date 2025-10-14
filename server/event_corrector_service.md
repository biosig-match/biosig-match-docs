---
service_name: "Event Corrector Service"
component_type: "service"
description: "DataLinker の後段で実行され、raw データからトリガを再解析してセッションイベントの時刻を補正するワーカー。"
inputs:
  - source: "RabbitMQ queue event_correction_queue"
    data_format: "AMQP message (JSON)"
    schema: |
      { session_id: string }
  - source: "HTTP クライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/jobs
      Body: { session_id: string }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: |
      - session_events (onset, event_id)
      - sessions (start_time, experiment_id)
      - session_object_links
      - raw_data_objects (object_id, timestamp_start_ms, sampling_rate)
  - source: "MinIO (raw-data bucket)"
    data_format: "Object GET"
    schema: |
      raw_data_objects.object_id に対応するバイナリ (.bin)
outputs:
  - target: "PostgreSQL"
    data_format: "SQL UPDATE"
    schema: |
      - UPDATE session_events SET onset_corrected_us
      - UPDATE sessions SET event_correction_status ('processing'|'completed'|'failed')
  - target: "監視クライアント"
    data_format: "HTTP JSON"
    schema: |
      GET /api/v1/health -> { status, rabbitmq_connected, db_connected, minio_connected, queue, timestamp }
      GET /health -> { status }
---

## 概要

Event Corrector は Bun で実装されたワーカーで、`DataLinker` 後にトリガベースの時刻補正を実行します。`event_corrector/src/domain/services/corrector.ts` が中心ロジックで、Zstandard を利用したバイナリ解析は不要になったため、MinIO から取得した `.bin` をそのまま扱います (`downloadAndDecompressObjects` 内で連結するだけ)。

## サービスの役割と主なユースケース

- **セッションイベントの高精度化**: Session Manager からアップロードされた CSV のオンセット値は概算 (アプリ内ストップウォッチ基準) のため、実際のトリガ信号と突き合わせてマイクロ秒精度に補正します。これにより BIDS での ERP 解析など時間精度の高い処理が可能になります。
- **不整合の検出**: トリガ本数とイベントレコード数が一致しない場合、ログとステータス (`failed`) に残し、運用者に調査を促します。CSV 側の抜け漏れや配線不良を早期に発見できます。
- **再処理のしきい値調整**: 解析中にチャネル品質やサンプルレートが想定と異なる場合でも、`SAMPLE_RATE` やマッチング許容時間を設定で調整し再キュー投入できます。試行錯誤しながら最適値を探れるように設計されています。
- **下流サービスへの準備**: 補正済みの `onset_corrected_us` をセットすることで、BIDS Exporter は追加計算なしに正確な events.tsv を生成できます。

## ランタイム構成

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 接続。 |
| `RABBITMQ_URL` | イベントキュー接続。 |
| `EVENT_CORRECTION_QUEUE` | 消費するキュー名。 |
| `MINIO_*` | raw データ取得用接続。 |
| `MINIO_RAW_DATA_BUCKET` | 既定 `raw-data`。 |
| `SAMPLE_RATE` | トリガ解析のデフォルトサンプリングレート (デバッグ用)。 |

## 処理フロー (`handleEventCorrectorJob` → `processCorrectionJob`)

1. トランザクション開始、`sessions.event_correction_status` を `processing` に更新。
2. 対象セッションの `session_events` を取得 (onset 昇順)。件数 0 の場合は `completed` にして終了。
3. `session_object_links` と `raw_data_objects` を JOIN し、関連オブジェクトの `object_id`, `timestamp_start_ms`, `sampling_rate` を取得。見つからなければ `completed`。
4. 各オブジェクトを MinIO からダウンロードし、payload を `parsePayloadsAndExtractTriggerTimestampsUs` へ渡してトリガ時刻 (マイクロ秒) を抽出。
5. 抽出トリガ数とイベント数を突き合わせ、近似的にマッチング (Δ0.5秒以内)。
6. `session_events.onset_corrected_us` を更新。増加単調性を維持できない場合は 1µs 進めて補正。
7. `sessions.event_correction_status` を `completed` に更新。
8. 例外発生時はロールバックし、ステータスを `failed` に更新。

## HTTP エンドポイント

| メソッド | パス | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/jobs` | 手動ジョブ投入。RabbitMQ チャンネルが未初期化なら 503。 |
| `GET` | `/api/v1/health` | RabbitMQ / DB / MinIO 状態を返却。 |
| `GET` | `/health` | 簡易ヘルスチェック。 |

## 参考ファイル

- ジョブ処理: `event_corrector/src/domain/services/corrector.ts`
- トリガ解析: `event_corrector/src/domain/services/trigger_timestamps.ts`
- キュー制御: `event_corrector/src/infrastructure/queue.ts`
- MinIO ラッパー: `event_corrector/src/infrastructure/minio.ts`
