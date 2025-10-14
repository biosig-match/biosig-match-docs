---
service_name: "Smartphone App"
description: "BLE データ収集、セッション運用、解析トリガ、アセット管理を一元化する Flutter 製モバイルクライアント。"

inputs:
  - source: "ファームウェア (BLE Notify)"
    data_format: "DeviceConfigPacket, ChunkedSamplePacket"
    schema: "ADS1299_EEG_NUS: 0xDD / 0x66 パケット (25 サンプル/チャンク)"
  - source: "ユーザー操作"
    data_format: "UI イベント"
    schema: "実験作成・選択、セッション開始/終了、刺激提示操作、BIDSエクスポート要求など"
  - source: "Realtime Analyzer Service"
    data_format: "HTTP GET (JSON)"
    schema: "GET /api/v1/users/{user_id}/analysis → Base64 画像 + チャネル品質"
  - source: "ERP Neuro-Marketing Service"
    data_format: "HTTP GET (JSON)"
    schema: "解析結果スナップショット"
  - source: "Session Manager Service"
    data_format: "HTTP GET (JSON)"
    schema: "実験・刺激・キャリブレーション情報"

outputs:
  - target: "Collector Service"
    data_format: "HTTP POST (JSON, multipart)"
    schema: |
      - POST /api/v1/data: Zstd 圧縮済みペイロード + メタデータ
      - POST /api/v1/media: multipart (file, session_id, timestamps...)
  - target: "Session Manager Service"
    data_format: "HTTP POST (JSON, multipart)"
    schema: |
      - POST /api/v1/experiments: 実験新規作成
      - POST /api/v1/sessions/start: セッション開始通知
      - POST /api/v1/sessions/end: metadata + events_log_csv (生成 or アップロード)
  - target: "BIDS Exporter Service"
    data_format: "HTTP POST"
    schema: "POST /api/v1/experiments/{experiment_id}/export"
  - target: "ERP Neuro-Marketing Service"
    data_format: "HTTP POST"
    schema: "POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze"
---

## 概要

Flutter (`lib/`) で実装されたモバイルアプリは、BLE 接続からサーバー連携までの運用フローを単一 UI で完結させます。複数 Provider により責務を分割し、セッションの開始・終了や刺激提示、リアルタイム解析の確認、BIDS エクスポート、ERP 解析リクエストまでをモジュール化しています。アプリ起動時に `.env` を読み込んでサーバー URL などの設定をロードし、`MultiProvider` 構成で依存関係を注入します (`main.dart`)。

## アーキテクチャ概要

| Provider | 役割 | 主な依存 |
| --- | --- | --- |
| `BleProvider` | BLE スキャン・接続、サンプルバッファ、Collector への payload 送信 | `flutter_blue_plus`, `AuthProvider`, `ServerConfig` |
| `SessionProvider` | 実験一覧・作成、セッション開始/終了 API 呼び出し | `AuthProvider`, `http` |
| `StimulusProvider` | 刺激メタデータ取得、MinIO 経由ダウンロード (Session Manager 経由) | `AuthProvider` |
| `MediaProvider` | カメラ・マイク制御、Collector へのメディア送信 | `camera`, `record`, `zstandard` |
| `AnalysisProvider` | Realtime Analyzer から PSD/コヒーレンス画像を取得 | `http` |
| `BidsProvider` | BIDS エクスポートの起動とタスクポーリング | `http`, `url_launcher` |
| `ErpAnalysisProvider` | ERP 解析リクエストと結果取得 | `http` |
| `AuthProvider` | `X-User-Id` ヘッダー管理 (現状はモック固定) | - |

UI は Drawer ナビゲーション (`AppDrawer`) と複数の画面 (`screens/`) で構成され、Provider の状態更新でリアクティブに描画されます。

## BLE スタック (`BleProvider`)

- **対応デバイス**: 自作 ESP32 (デバイス名 `ADS1299_EEG_NUS*`)、Muse 2。
- **スキャン**: `FlutterBluePlus.startScan()` を呼び出し、デバイス名に応じてフィルタ。10 秒でタイムアウト。
- **カスタム EEG**:
  - サービス/キャラクタリスティック UUID を探索し、TX を Notify、RX を Write に設定。
  - 接続直後に `0xAA` を送ってファームウェアへストリーミングを要求。
  - 受信データを `DeviceConfigPacket` と `ChunkedSamplePacket` に振り分け、電極構成やサンプルを解析。
  - 250 サンプルごとに Collector向けペイロードを生成し、Zstandard で圧縮して `POST /api/v1/data` へ送信。
- **Muse 2**:
  - 複数キャラクタリスティックから 12 ビット EEG データを分解し、チャンネルごとにバッファリング。
  - Preset コマンド (`p21`, `s`, `d`) を送信してストリーミングを開始。
- **共通処理**:
  - `_displayDataBuffer` を最大 5 秒分保持し、UI `EegChart` で波形を描画。
  - 左右脳波の相対パワー差から簡易バレンススコアを算出し、`ValenceChart` に履歴を提供。
  - Collector 送信バッチにはチャネルラベルやトリガ状態を含むヘッダー (format v4) を付与。

## セッション管理 (`SessionProvider`)

1. **実験一覧取得**: 起動時に `GET /api/v1/experiments` を呼び出し、参加可能な実験をキャッシュ。
2. **実験作成**: ダイアログから名称・説明・提示順を受け取り、`POST /api/v1/experiments` を実行。必要に応じて刺激 CSV/ファイルを `POST /api/v1/experiments/{id}/stimuli` へ multipart 送信。
3. **セッション開始**:
   - BLE 接続中のデバイス ID と任意の `clock_offset_info` を添えて `POST /api/v1/sessions/start` を実行。
   - フリーセッションを許容しつつ、実験選択時は `experiment_id` を付与。
4. **セッション終了**:
   - `StimulusPresentationScreen` で生成した CSV 文字列、またはユーザーが選択した CSV ファイルを添付し、`POST /api/v1/sessions/end` を multipart 送信。
   - 正常終了後、`SessionSummaryScreen` で UI をクローズしホームへ戻る。

## 刺激提示 (`StimulusPresentationScreen`)

- セッション種別に応じてキャリブレーション項目または実験刺激をロードし、必要な画像を事前ダウンロード (`StimulusProvider` のキャッシュ機構)。
- 実験設定が `random` の場合は提示順をシャッフル。
- 1 秒提示 → 1.5 秒待機を繰り返し、Stopwatch から算出したオンセットをイベントログに記録。
- セッション完了時に `onset,duration,trial_type,file_name` の CSV を生成し、`SessionSummaryScreen` に渡して自動アップロード。

## メディアキャプチャ (`MediaProvider`)

- セッション開始を監視し、10 秒周期で以下を実行:
  1. 5 秒間の音声録音 (`record` パッケージ)。
  2. 中間で静止画を撮影 (`camera` パッケージ)。
  3. 録音終了後に Zstd 圧縮 (可能なら) を行い、Collector の `/api/v1/media` へ multipart 送信。
- 画像は `timestamp_utc`、音声は `start_time_utc` / `end_time_utc` を付加し、Collector 側で DataLinker との連携が取れるようにしています。

## リアルタイム解析 (`AnalysisProvider` / `AnalysisScreen`)

- 解析画面表示時に 10 秒周期のポーリングを開始し、`GET /api/v1/users/{user_id}/analysis` を呼び出します。
- 成功時は PSD・コヒーレンス画像の Base64 をデコードし、`AnalysisImageViewer` で表示。
- 202 応答やエラー時はステータスメッセージに反映し、接続障害をユーザーへ通知します。

## BIDS エクスポート (`BidsProvider`, `BidsExportScreen`)

- 実験カードのアクションから `POST /api/v1/experiments/{experiment_id}/export` を起動。
- 戻り値の `task_id` と `status_url` を保存し、5 秒間隔でタスク状態をポーリング。
- 完了後は `downloadBidsFile` で `/api/v1/export-tasks/{task_id}/download` を外部ブラウザで開きます。

## ERP 解析 (`ErpAnalysisProvider`, `NeuroMarketingScreen`)

- 最新結果の取得: `GET /api/v1/neuro-marketing/experiments/{experiment_id}/analysis-results`。
- 解析リクエスト: `POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze`。成功後に再取得をトリガー。
- Provider は実験 ID ごとにキャッシュし、UI にステータスメッセージを掲出します。

## Collector へのデータ送信

BLE からのサンプルは `_serverUploadBuffer` に蓄積され、250 サンプルが揃うたびに以下を実施します。

1. ヘッダー (フォーマット v4) とサンプル行列、トリガ、空の IMU/インピーダンスプレースホルダを組み立て。
2. `zstandard` の WASM バインディングで圧縮。
3. `{ payload_base64, sampling_rate, lsb_to_volts, device_id, session_id? }` を JSON 化して Collector へ送信。

送信失敗時はログに残し、リトライは次バッチ送信時に任せる設計です。

## 依存関係と設定

- `.env` に `HTTP_BASE_URL` などを定義 (`ServerConfig.fromEnv`)。
- 権限: 起動時に BLE/位置情報/カメラ/マイク権限をまとめて要求 (`permission_handler`)。
- UI テーマ: ダークテーマ固定で、シアン系アクセントカラーを採用 (`ThemeData.dark()` ベース)。

## 想定する運用シナリオ

1. BLE デバイスを選択して接続 → データストリームと波形表示を確認。
2. 実験を選択し、キャリブレーション/本番刺激をアプリ内で提示 → 自動的にイベントログ生成。
3. セッション終了時に CSV とメディアがアップロードされ、サーバー側で DataLinker → Event Corrector → BIDS Exporter へと処理が連鎖。
4. Operator はモバイルアプリ上から BIDS エクスポートや ERP 解析を走らせ、結果をレビュー。
