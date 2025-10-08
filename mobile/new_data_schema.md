はい、承知いたしました。
提示されたスマホアプリ（Dart）とマイコン（C++）のコードを完全に反映し、サーバー受信データスキーマ仕様書を最新版に修正します。

-----

# サーバー受信データスキーマ仕様

## 1\. 概要

本仕様書は、クライアント（スマホアプリ）からサーバーへ送信される JSON ペイロード内の `payload_base64` フィールドをデコード・解凍した後に得られる、バイナリデータの構造を定義する。

  - **外部 JSON 構造:**

    ```json
    {
      "user_id": "string",
      "session_id": "string | null",
      "device_id": "string",
      "timestamp_start_ms": "integer",
      "timestamp_end_ms": "integer",
      "payload_base64": "string"
    }
    ```

      - `session_id`はセッション中以外は `null` となる。

  - **内部バイナリデータ:**

      - `payload_base64` は、以下の仕様で定義されるバイナリデータを **Zstandard** で圧縮し、**Base64** でエンコードしたものである。
      - データは、**単一のヘッダーブロック**と、それに続く**250 個のサンプルデータブロック**で構成される連続したバイナリ ストリームである。
      - 全ての数値は **リトルエンディアン** 形式とする。

-----

## 2\. データ全体構造

ペイロード全体のレイアウトは以下の通り。

**[ヘッダーブロック] + ([サンプルデータブロック] x 250 回)**

-----

## 3\. ヘッダーブロック仕様

ペイロードの先頭に 1 つだけ存在する固定長のブロック。このペイロードに含まれるデータの定義情報を持つ。

| フィールド名 | データ型 | サイズ(Bytes) | 説明 |
| :--- | :--- | :--- | :--- |
| `version` | `uint8_t` | 1 | このペイロード構造のバージョン。現行は `0x02`。 |
| `num_channels` | `uint8_t` | 1 | チャンネルの総数。**自作脳波計: 9, Muse 2: 4**。 |
| `reserved` | `uint8_t[6]` | 6 | 将来のための予約領域。`0x00` で埋める。 |
| `electrode_config` | `struct`配列 | `num_channels` \* 10 | 各電極の設定情報。詳細は下記参照。 |

#### `electrode_config` 構造体 (10 Bytes)

`num_channels` の数だけ繰り返される。

| フィールド名 | データ型 | サイズ(Bytes) | 説明 |
| :--- | :--- | :--- | :--- |
| `name` | `char[8]` | 8 | 電極名 (例: "CH1", "TP9")。UTF-8 エンコード、未使用分は `\0` (ヌル文字)で埋める。 |
| `type` | `uint8_t` | 1 | 電極タイプ。<br> `0`: EEG, `1`: EMG, `2`: EOG, `3`: TRIG, `255`: UNKNOWN |
| `reserved` | `uint8_t` | 1 | 予約領域。`0x00` で埋める。 |

-----

## 4\. サンプルデータブロック仕様

ヘッダーブロックの直後から、1 サンプル分のデータブロックが 250 回繰り返される。
ブロックの合計サイズは、**自作脳波計の場合 39 Bytes**、**Muse 2 の場合 24 Bytes** となる。

| フィールド名 | データ型 | サイズ(Bytes) | 説明 |
| :--- | :--- | :--- | :--- |
| `signals` | `int16_t`配列 | `num_channels` \* 2 | 全チャンネルの信号値。`electrode_config`の順序に対応する。<br>**自作脳波計**: 8chのEEG信号 + 1chのトリガー状態。<br>**Muse 2**: 4chのEEG信号。 |
| `accel` | `int16_t[3]` | 6 | 加速度 (X, Y, Z)。**常に `0x00` で埋められる。** |
| `gyro` | `int16_t[3]` | 6 | ジャイロ (X, Y, Z)。**常に `0x00` で埋められる。** |
| `impedance` | `uint8_t`配列 | `num_channels` | 全チャンネルのインピーダンス。<br>**常に無効値 `255` (UNKNOWN) で埋められる。** |

-----

## 5\. デバイス別データマッピング

スマホアプリがデバイス間の差異を吸収し、サーバーには常に本仕様に準拠したバイナリ構造のデータを送信する。

| フィールド | 自作脳波計 | Muse 2 (4ch) |
| :--- | :--- | :--- |
| **ヘッダー** | | |
| `num_channels` | **固定値: `9`** | **固定値: `4`** |
| `electrode_config` | マイコンから受信した8ch設定 + **アプリが付与する `{"TRIG", type:3}`** | **アプリが生成する固定設定:**<br> `[{"TP9", 0}, {"AF7", 0}, {"AF8", 0}, {"TP10", 0}]` |
| **サンプルデータ** | | |
| `signals` | 9ch分のデータ (`int16_t` x 9)。<br>1-8ch: EEG信号<br>9ch目: トリガー状態 (値は 0-15) | 4ch分のデータ (`int16_t` x 4)。<br>12bitの生データ (0-4095) が格納される。 |
| `accel` | **常に `0x00` で埋められる** | **常に `0x00` で埋められる** |
| `gyro` | **常に `0x00` で埋められる** | **常に `0x00` で埋められる** |
| `impedance` | **常に `255` (UNKNOWN) で埋められる** | **常に `255` (UNKNOWN) で埋められる** |

-----

## 6\. バイナリデータ例 (ペイロードの先頭部分)

#### 例 1: 自作脳波計の場合

  - **Header (98 bytes)** + **Sample[0] (39 bytes)** + ...

<!-- end list -->

```
// Header Block
02                      // version: 2
09                      // num_channels: 9
00 00 00 00 00 00       // reserved
// electrode_config[0] ("CH1", EEG)
43 48 31 00 00 00 00 00 00 00
... (残り7ch分続く) ...
// electrode_config[8] ("TRIG", TRIG) - アプリが付与
54 52 49 47 00 00 00 00 03 00

// Sample Data Block [0]
// signals[9] (18 bytes)
XX XX XX XX XX XX XX XX // 8ch分のEEGデータ (16 bytes)
XX XX                   // 9ch目のトリガー状態 (2 bytes)
// accel[3] + gyro[3] (12 bytes)
00 00 00 00 00 00 00 00 00 00 00 00
// impedance[9] (9 bytes)
FF FF FF FF FF FF FF FF FF

// Sample Data Block [1]
... (39 bytes) ...
```

#### 例 2: Muse 2 (4ch) の場合

  - **Header (48 bytes)** + **Sample[0] (24 bytes)** + ...

<!-- end list -->

```
// Header Block
02                      // version: 2
04                      // num_channels: 4
00 00 00 00 00 00       // reserved
// electrode_config[0] ("TP9", EEG)
54 50 39 00 00 00 00 00 00 00
// electrode_config[1] ("AF7", EEG)
41 46 37 00 00 00 00 00 00 00
... (残り2ch分続く) ...

// Sample Data Block [0]
// signals[4] (8 bytes)
XX XX XX XX XX XX XX XX
// accel[3] + gyro[3] (12 bytes)
00 00 00 00 00 00 00 00 00 00 00 00
// impedance[4] (4 bytes)
FF FF FF FF

// Sample Data Block [1]
... (24 bytes) ...
```
