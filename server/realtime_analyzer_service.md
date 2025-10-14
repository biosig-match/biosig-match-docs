---
service_name: "Realtime Analyzer Service"
component_type: "service"
description: "RabbitMQ からリアルタイムの生データを受信し、チャンネル品質評価と周波数解析を行いながら最新結果を API で提供する Flask アプリ。"
inputs:
  - source: "RabbitMQ exchange raw_data_exchange"
    data_format: "AMQP message"
    schema: |
      Queue: analysis_queue (fanout)
      Headers:
        user_id: string
        session_id?: string
        sampling_rate: number
        lsb_to_volts: number
      Body: zstd 圧縮バイナリ (payload format v4)
  - source: "Configuration"
    data_format: "env"
    schema: |
      SAMPLE_RATE, ANALYSIS_WINDOW_SEC, ANALYSIS_INTERVAL_SECONDS など解析パラメータ
outputs:
  - target: "HTTP クライアント"
    data_format: "JSON"
    schema: |
      GET /api/v1/users/{user_id}/analysis ->
        {
          "spectral_psd_png_base64": string,
          "connectivity_png_base64": string,
          "channel_quality": {
            channel_name: {
              status: 'good'|'bad',
              reasons: string[],
              zero_ratio: number,
              bad_impedance_ratio: number,
              unknown_impedance_ratio: number,
              flatline: boolean,
              type: string,
              has_warning: boolean
            }
          },
          "generated_at": ISO8601
        }
      データ未準備時は 202 + {status: "..."}
  - target: "監視クライアント"
    data_format: "JSON"
    schema: |
      GET /health -> {status:'ok'|'unhealthy'}
---

## 概要

Realtime Analyzer は Flask で提供される軽量 API で、バックグラウンドスレッド (`rabbitmq_consumer`, `analysis_worker`) が RabbitMQ と解析ループを担当します。`numpy`, `mne`, `mne-connectivity` を使用して PSD とコヒーレンスを計算し、結果を Base64 画像として保持します。

## サービスの役割と主なユースケース

- **現場での品質確認**: 計測中にチャンネル品質や PSD グラフを確認し、電極の浮き・雑音などをその場で検知できます。UI は 10 秒単位で更新され、モバイルアプリ上で即座にフィードバックされます。
- **デバイスプロファイルの保持**: BLE から受信した電極ラベルや LSB-to-Volts 係数を記憶し、解析時に正しいスケーリングを適用します。異なるデバイスを切り替えてもユーザー ID 単位で状態が保たれます。
- **軽量 API 提供**: 結果は Base64 PNG と JSON で返却されるため、Web フロントエンドや CLI ツールが簡単に取り込み・表示できます。解析を重いバッチ処理に頼らず、Younger UI で活用可能です。
- **バッファリングによるデータ保護**: RabbitMQ 障害時でも一定時間分（最大 60 秒）のデータがメモリに残るため、再接続後に解析が再開できます。解析ループはバックオフ付きで動作し、停止しません。

## ランタイム構成

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `RABBITMQ_URL` | `amqp://guest:guest@rabbitmq:5672` | AMQP 接続。 |
| `ANALYSIS_WINDOW_SEC` | `2.0` | 解析に使用する最新データ時間 (秒)。 |
| `ANALYSIS_INTERVAL_SECONDS` | `10` | 解析ループの実行間隔。 |
| `CHANNEL_*` | 複数 | チャンネル品質判定しきい値。 |

## メッセージ処理

1. fanout exchange `raw_data_exchange` に対し `analysis_queue` を宣言・バインド。
2. 受信バイナリを zstd 展開し、`parse_eeg_binary_payload_v4` でヘッダ (`ch_names`, `ch_types`) とサンプル配列 (`signals`, `impedance`) に分解。
3. ユーザーごとのバッファ (`user_data_buffers`) とデバイスプロファイル (`user_device_profiles`) を更新。チャンネル品質は `ChannelQualityTracker` で追跡。
4. バッファは 60 秒分を上限として保持し、古いデータを自動的にトリム。

## 解析ループ

- `analysis_worker` スレッドが `analysis_interval_seconds` ごとに実行。
- `analysis_window_seconds` 相当の最新データを抽出し、`mne.io.RawArray` を生成。
- 手順:
  1. 悪いチャネルを除外。
  2. `compute_psd` でパワースペクトル密度 (1–45Hz) を算出し、Matplotlib で画像化。
  3. `spectral_connectivity_epochs` を用いてアルファ帯域 (8–13Hz) のコヒーレンスを計算し、`plot_connectivity_circle` で可視化。
  4. `latest_analysis_results[user_id]` に画像とメタデータ (生成時刻、使用チャネル) を格納。

## API

### `GET /api/v1/users/{user_id}/analysis`

- ロック (`analysis_lock`) を取り最新解析結果を参照。
- 結果が無ければ 202 + `{ "status": "ユーザー(...)の解析結果はまだありません..." }` を返却。
- 結果があれば 200 で Base64 画像とチャネルレポートを返却。

### `GET /health`

- RabbitMQ 接続イベント (`rabbitmq_connected_event`) がセットされていれば 200、未接続なら 503。

## 参考ファイル

- Flask サーバー: `realtime_analyzer/src/app/server.py`
- 解析ロジック: `realtime_analyzer/src/domain` (現時点ではサーバーファイル内に集約)
- 設定: `realtime_analyzer/src/config/env.py`
