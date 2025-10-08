-----

# サーバー受信データスキーマ仕様

## 1\. 概要

本仕様書は、クライアント（スマホアプリ）からサーバーへ送信される JSON ペイロードの構造と、その `payload_base64` フィールドをデコード・解凍した後に得られるバイナリデータの構造を定義します。

**外部 JSON 構造:**
物理的なデバイス特性（サンプリングレート、電圧変換係数）はJSONのトップレベルフィールドとして送信されます。

```json
{
  "user_id": "string",
  "session_id": "string | null",
  "device_id": "string",
  "timestamp_start_ms": "integer",
  "timestamp_end_ms": "integer",
  "sampling_rate": "number",
  "lsb_to_volts": "number",
  "payload_base64": "string"
}
```

**内部バイナリデータ:**
`payload_base64` は、以下の仕様で定義されるバイナリデータを **Zstandard** で圧縮し、**Base64** でエンコードしたものです。 データは、単一のヘッダーブロックと、それに続く **JSONで指定された `sampling_rate` と同数のサンプルデータブロック**（約1秒分）で構成される連続したバイナリストリームです。 全ての数値は **リトルエンディアン** 形式とします。

-----

## 2\. データ全体構造

ペイロード全体のレイアウトは以下の通りです。

`[ヘッダーブロック] + ([サンプルデータブロック] x N 回)`

**※ NはJSONで指定される `sampling_rate` の整数値です (例: 250, 256)。**

-----

## 3\. ヘッダーブロック仕様

ペイロードの先頭に1つだけ存在するブロックです。このペイロードに含まれるチャンネル構成の定義情報を持ちます。

| フィールド名 | データ型 | サイズ(Bytes) | 説明 |
| :--- | :--- | :--- | :--- |
| `version` | `uint8_t` | 1 | このペイロード構造のバージョン。現行は **`0x04`**。 |
| `num_channels` | `uint8_t` | 1 | チャンネルの総数 (例: 自作脳波計: 9, Muse 2: 4)。 |
| `reserved` | `uint8_t[2]` | 2 | 将来のための予約領域。`0x00` で埋める。 |
| `electrode_config` | `struct`配列 | `num_channels` \* 10 | 各電極の設定情報。詳細は下記参照。 |

#### `electrode_config` 構造体 (10 Bytes)

`num_channels` の数だけ繰り返されます。

| フィールド名 | データ型 | サイズ(Bytes) | 説明 |
| :--- | :--- | :--- | :--- |
| `name` | `char[8]` | 8 | 電極名 (例: `"CH1"`, `"TP9"`)。UTF-8、未使用分は `\0`。 |
| `type` | `uint8_t` | 1 | 電極タイプ。<br> `0`: EEG, `1`: EMG, `2`: EOG, `3`: TRIG, `255`: UNKNOWN |
| `reserved` | `uint8_t` | 1 | 予約領域。`0x00` で埋める。 |

-----

## 4\. サンプルデータブロック仕様

ヘッダーブロックの直後から、1サンプル分のデータブロックが **N回（`sampling_rate` と同数）** 繰り返されます。

| フィールド名 | データ型 | サイズ(Bytes) | 説明 |
| :--- | :--- | :--- | :--- |
| `signals` | `int16_t`配列 | `num_channels` \* 2 | 全チャンネルの信号値 (ADC raw value)。 |
| `accel` | `int16_t[3]` | 6 | 加速度 (X, Y, Z)。常に `0x00` で埋められる。 |
| `gyro` | `int16_t[3]` | 6 | ジャイロ (X, Y, Z)。常に `0x00` で埋められる。 |
| `impedance` | `uint8_t`配列 | `num_channels` | 全チャンネルのインピーダンス。常に `255` (UNKNOWN) で埋められる。 |

-----

## 5\. デバイス別データマッピング例

| フィールド | 自作脳波計 | Muse 2 (4ch) |
| :--- | :--- | :--- |
| **JSON** | | |
| `sampling_rate` | 250.0 | 256.0 |
| `lsb_to_volts` | 5.722e-7 | 4.8828125e-7 |
| **ヘッダー** | | |
| `num_channels` | 9 | 4 |
| `electrode_config` | 8ch設定 + `{"TRIG", type:3}` | `[{"TP9",0}, {"AF7",0}, ...]` |
| **サンプルデータ** | | |
| `signals` | 8ch EEG + 1ch Trigger (`int16_t`) | 4ch EEG (`int16_t`, 12bit値を格納) |
| **サンプル数 (N)** | **250** | **256** |

-----

## 6\. バイナリデータ例 (ペイロードの先頭部分)

#### 例 1: 自作脳波計の場合

`Header (94 bytes) + Sample[0] (39 bytes) + ... + Sample[249] (39 bytes)`

```
// Header Block
04                         // version: 4
09                         // num_channels: 9
00 00                      // reserved
// electrode_config[0] ("CH1", EEG)
43 48 31 00 00 00 00 00 00 00
... (残り7ch分続く) ...
// electrode_config[8] ("TRIG", TRIG)
54 52 49 47 00 00 00 00 03 00

// Sample Data Block [0]
// signals[9] (18 bytes)
XX XX XX XX XX XX XX XX XX XX XX XX XX XX XX XX XX XX
// accel[3] + gyro[3] (12 bytes)
00 00 00 00 00 00 00 00 00 00 00 00
// impedance[9] (9 bytes)
FF FF FF FF FF FF FF FF FF
...
```

#### 例 2: Muse 2 (4ch) の場合

`Header (44 bytes) + Sample[0] (24 bytes) + ... + Sample[255] (24 bytes)`

```
// Header Block
04                         // version: 4
04                         // num_channels: 4
00 00                      // reserved
// electrode_config[0] ("TP9", EEG)
54 50 39 00 00 00 00 00 00 00
... (残り3ch分続く) ...

// Sample Data Block [0]
// signals[4] (8 bytes)
XX XX XX XX XX XX XX XX
// accel[3] + gyro[3] (12 bytes)
00 00 00 00 00 00 00 00 00 00 00 00
// impedance[4] (4 bytes)
FF FF FF FF
...
```
