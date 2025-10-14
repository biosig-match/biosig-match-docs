---
service_name: "Firmware (ESP32)"
description: "ADS1299 ベースの EEG ボードを制御し、BLE (Nordic UART Service 互換) でデータをチャンク送信する組み込みファームウェア。"
inputs:
  - source: "ADS1299 (SPI)"
    data_format: "SPI RDATAC ストリーム (24bit/CH)"
    schema: "CH1-CH8, GPIO ステータス下位 4bit"
  - source: "スマートフォンアプリ (BLE Write)"
    data_format: "Control コマンド"
    schema: "{ CMD_START_STREAMING(0xAA) | CMD_STOP_STREAMING(0x5B) }"
outputs:
  - target: "スマートフォンアプリ (BLE Notify)"
    data_format: "DeviceConfigPacket (0xDD)"
    schema: "LE packed struct: { num_channels, ElectrodeConfig[8] }"
  - target: "スマートフォンアプリ (BLE Notify)"
    data_format: "ChunkedSamplePacket (0x66)"
    schema: "25 サンプル分の SampleData を含む固定長 504 byte ペイロード"
---

## 概要

このファームウェアは ESP32 上で動作し、ADS1299 のマルチチャンネル EEG データを 250 Hz で取得して BLE 経由でストリーミングします。NUS 互換のサービス UUID を採用し、スマートフォン側は `0xAA`/`0x5B` の単一バイトコマンドで計測開始・停止を制御します。計測開始時にはチャンネル構成を通知し、以降は 25 サンプル（0.1 秒）単位でチャンク化したサンプル列を通知します。

## ハードウェアとピン割り当て

| 種別 | 役割 | ピン |
| --- | --- | --- |
| SPI CS | ADS1299 チップセレクト | `D1` (`PIN_SPI_CS`) |
| DRDY | 新規サンプル準備完了割込み | `D0` (`PIN_DRDY`) |
| SPI 設定 | `SPI_MODE1`, `MSBFIRST`, `1MHz` | `ads1299_spi_settings` |

DRDY が Low になったタイミングでサンプルを読み出し、24bit の変換値を 16bit に縮退して保持します。未使用チャンネルは 0 でパディングします。

## 初期化シーケンス

1. `Serial.begin(115200)` でデバッグログを有効化。
2. BLE を `DEVICE_NAME = "ADS1299_EEG_NUS"` で初期化し、NUS 互換サービスを起動。
3. SPI を初期化し、ADS1299 に対して以下を実行:
   - `SDATAC` → `RESET` → `detectChannelCount()` によるチャネル数検出 (4/6/8)。
   - `CONFIG1=0x96` (250 SPS), `CONFIG3=0xE0` (内部リファレンス)。
   - 有効チャンネルに `0x60` (Gain ×24, 正常入力)、未使用チャンネルに `0x81` (電源断)。
   - `START` → `RDATAC` で連続変換モードへ移行。
4. 初期化完了後、BLE アドバタイジングを再開して接続待ち。

## BLE サービス構成

| UUID | 用途 | プロパティ |
| --- | --- | --- |
| `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | サービス UUID | - |
| `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | TX (通知) | Notify |
| `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` | RX (制御) | Write |

BLE サーバーコールバックで接続状態を監視し、切断時はストリーミング状態を自動でリセットします。`CMD_START_STREAMING` を受信するとバッファを初期化し、次回ループでデバイス設定パケットを通知します。`CMD_STOP_STREAMING` を受信するとフラグを落として計測を停止します。

## ストリーミング処理

- **サンプリング周期**: 250 Hz（ADS1299 側設定）。
- **チャンクサイズ**: 25 サンプル（10 Hz 通知）。
- **バッファ**: `SampleData sampleBuffer[25]` にリング状に蓄積。
- **通知間隔**: `BLE_NOTIFY_INTERVAL_MS = 100` を満たす場合にのみ BLE 通知を送信し、スタックの処理時間確保のため 10 ms のディレイを入れます。
- **トリガ状態**: `GPIO` 下位 4bit を `trigger_state` として保持し、将来の外部刺激同期に備えて `reserved[3]` を確保しています。

ループ内では DRDY を監視してサンプル読み出し (`readOneAds1299Sample`) を行い、チャンクが埋まったタイミングで `ChunkedSamplePacket` を TX characteristic に設定して通知します。計測中でない場合は 10 ms スリープして BLE タスクに CPU を譲ります。

## パケットフォーマット

### DeviceConfigPacket (0xDD)

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `packet_type` | `uint8` | 固定値 `0xDD` |
| `num_channels` | `uint8` | 検出した有効 EEG チャンネル数 (4/6/8) |
| `reserved` | `uint8[6]` | 将来拡張用 (0 埋め) |
| `configs[8]` | `ElectrodeConfig` | 8 エントリの固定配列 |

`ElectrodeConfig` は `char name[8]` + `uint8 type` + `uint8 reserved`。現行実装では `CH1`〜`CH8`, `type=0`（EEG）で初期化されます。

### ChunkedSamplePacket (0x66)

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `packet_type` | `uint8` | 固定値 `0x66` |
| `start_index` | `uint16 LE` | チャンク先頭サンプルの通番 |
| `num_samples` | `uint8` | 固定 25 |
| `samples` | `SampleData[25]` | サンプル列 |

`SampleData` は下記構造体 (LE):

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `signals[8]` | `int16` | 各チャネルの EEG 値 (左詰め、未使用は 0) |
| `trigger_state` | `uint8` | ADS1299 GPIO 下位 4bit |
| `reserved[3]` | `uint8` | 拡張用 (IMU 等) |

パケット長は常に 504 byte で、スマートフォン側の受信ハンドラでスライス処理が容易になるよう固定されています。

## エラーハンドリングとログ

- `readOneAds1299Sample` は DRDY が High の場合 `false` を返し、ループ側で 1 ms スリープして busy loop を避けます。
- BLE 通知/書き込みエラーは `Serial.println` でロギングされます（例: 停止コマンド受信時）。
- 定期ハートビート (`loop_counter % 500000 == 0`) で接続状態とストリーミング状態をシリアルに出力し、スタックが停止していないかを確認できます。

## 拡張ポイント

- **IMU 連携**: `SampleData.reserved` を利用すれば IMU データを追加できる設計です。パケットサイズを維持する場合は 6 byte 程度まで追加可能です。
- **チャネルラベル**: 現在は固定 `CH1`〜`CH8` ですが、将来的に BLE 経由でラベルを変更して `DeviceConfigPacket` に反映する余地があります。
- **トリガ入力**: `trigger_state` は GPIO の生値を送出するのみです。閾値判定等を追加する場合は DRDY 読み出し後に処理を挟んでください。
