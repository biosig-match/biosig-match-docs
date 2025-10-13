---
service_name: "RabbitMQ"
component_type: "queue"
description: "Collector からのストリームデータとサービス間ジョブを仲介するメッセージブローカー。fanout exchange と複数キューで構成される。"
inputs:
  - source: "Collector Service"
    data_format: "AMQP publish"
    schema: |
      Exchange: raw_data_exchange (fanout)
      Routing key: '' (全購読者へ配信)
      Payload: zstd 圧縮バイナリ、ヘッダーに計測メタデータ
  - source: "Session Manager Service"
    data_format: "AMQP sendToQueue"
    schema: |
      - Queue: stimulus_asset_queue -> { experiment_id, csvDefinition[], files[] }
      - Queue: data_linker_queue -> { session_id }
  - source: "DataLinker Service"
    data_format: "AMQP sendToQueue"
    schema: |
      Queue: event_correction_queue -> { session_id }
outputs:
  - target: "Processor Service"
    data_format: "AMQP consume"
    schema: |
      Queue: processing_queue (raw_data_exchange fanout)
  - target: "Realtime Analyzer Service"
    data_format: "AMQP consume"
    schema: |
      Queue: analysis_queue (raw_data_exchange fanout)
  - target: "Media Processor Service"
    data_format: "AMQP consume"
    schema: |
      Queue: media_processing_queue
  - target: "Stimulus Asset Processor Service"
    data_format: "AMQP consume"
    schema: |
      Queue: stimulus_asset_queue
  - target: "DataLinker Service"
    data_format: "AMQP consume"
    schema: |
      Queue: data_linker_queue
  - target: "Event Corrector Service"
    data_format: "AMQP consume"
    schema: |
      Queue: event_correction_queue
---

## 概要

RabbitMQ は raw ストリームとジョブキューを単一ブローカーで扱います。主要構成要素:

- **Exchange `raw_data_exchange` (fanout)**: Collector から受信したセンサーデータを Processor / Realtime Analyzer へブロードキャスト。
- **Queue `media_processing_queue`**: Collector → Media Processor のメディア転送。
- **Queue `stimulus_asset_queue`**: Session Manager → Stimulus Asset Processor の刺激登録ジョブ。
- **Queue `data_linker_queue`**: Session Manager → DataLinker のセッション後処理ジョブ。
- **Queue `event_correction_queue`**: DataLinker → Event Corrector のトリガ補正ジョブ。

## キュー設定

| キュー名 | 宣言元 | 消費者 | 特記事項 |
| --- | --- | --- | --- |
| `processing_queue` | Processor (起動時) | Processor | `channel.prefetch(1)` で逐次処理。fanout で raw_data_exchange にバインド。 |
| `analysis_queue` | Realtime Analyzer | Realtime Analyzer | fanout でバインド。再接続時に再宣言。 |
| `media_processing_queue` | Collector | Media Processor | durable。Collector が publish 前に assert。 |
| `stimulus_asset_queue` | Session Manager | Stimulus Asset Processor | ジョブは JSON 文字列。 |
| `data_linker_queue` | Session Manager | DataLinker | ジョブは `{session_id}`。 |
| `event_correction_queue` | DataLinker | Event Corrector | ジョブは `{session_id}`。 |

## メッセージ仕様

### raw データメッセージ

- `properties.headers`: 計測メタデータ (`user_id`, `device_id`, `timestamp_*_ms`, `sampling_rate`, `lsb_to_volts`, `session_id?`)。
- `properties.contentType`: `application/octet-stream`
- `properties.contentEncoding`: `zstd`
- 処理フロー: Collector → fanout exchange → Processor / Realtime Analyzer。

### メディアメッセージ

- Headers にメディアメタデータ (`timestamp_utc` など) を格納。
- ボディはファイルの raw バイナリ。
- `persistent: true` で送信。

### ジョブメッセージ

- Session Manager / DataLinker から送信される JSON を文字列化し、`persistent: true` でキューへ送信。
- 各コンシューマは Zod / Pydantic で検証後、失敗時は `nack` で再試行または破棄します。

## エラーハンドリング戦略

- 各サービスは接続断検知時に指数バックオフで再接続 (`scheduleReconnect`) を実装。
- 重要キュー (stimulus_asset_queue, data_linker_queue, event_correction_queue) は durable。メッセージは `persistent: true` で送信されるため、ブローカー再起動時も保持されます。

## 参考

- Collector 実装: `collector/src/app/server.ts`
- Session Manager キュー送信: `session_manager/src/infrastructure/queue.ts`
- DataLinker / Event Corrector: それぞれの `infrastructure/queue.ts`
