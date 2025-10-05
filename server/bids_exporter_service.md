---
service_name: "BIDS Exporter Service"
description: "指定された実験の完了済みセッションデータを収集し、BIDS形式のデータセットとしてパッケージングするサービス。公開用の非同期APIと、内部サービス用の同期APIの2系統を提供する。"

# --- Public API (for external clients) ---
inputs:
  - source: "External Client (e.g., Web Dashboard)"
    data_format: "HTTP POST"
    schema: "`POST /api/v1/experiments/{experiment_id}/export` (body is empty)"
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "実験、セッション、イベント、刺激定義のメタデータ。`sessions.event_correction_status = 'completed'` のセッションのみ対象。"
  - source: "MinIO"
    data_format: "Object GET"
    schema: "セッションに対応する生データ（`raw_data_bucket`）と、実験刺激として登録されたメディアファイル（`media_bucket`）"

outputs:
  - target: "MinIO (`bids_bucket`)"
    data_format: "ZIP Archive"
    schema: "BIDS形式のディレクトリ構造を持つ圧縮済みデータセット。例: `eid_{experiment_id}.zip`"
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`export_tasks`テーブルにタスクの状態（pending, processing, completed, failed）、進捗、結果パスを記録する。"

# --- Internal API (for erp_neuro_marketing_service) ---
internal_inputs:
  - source: "ERP Neuro-Marketing Service"
    data_format: "HTTP POST (JSON)"
    schema: "`POST /internal/v1/create-bids-for-analysis` with body `{"experiment_id": "..."}`"

internal_outputs:
  - target: "Shared Volume"
    data_format: "File System Write"
    schema: "指定された`output_dir`にBIDS形式のディレクトリ構造を直接生成する（非圧縮）。"
  - target: "ERP Neuro-Marketing Service"
    data_format: "HTTP Response (JSON)"
    schema: "`{"bids_path": "/path/to/bids_dataset"}` を同期的に返す。"
---

## 概要

`BIDS Exporter`は、指定された実験のデータを収集し、標準化されたBIDS (Brain Imaging Data Structure) 形式のデータセットを生成するサービスです。本サービスは2つの異なるユースケースに対応するため、2系統のAPIを提供します。

1.  **公開API (Asynchronous)**: 外部クライアント（Webダッシュボードなど）向けの非同期API。エクスポート処理をバックグラウンドで実行し、生成されたBIDSデータセットをZIPファイルとしてMinIOに保存します。クライアントはタスクIDを使って進捗をポーリングし、完了後に結果をダウンロードできます。

2.  **内部API (Synchronous)**: `ERP Neuro-Marketing Service`のような内部サービス向けの同期API。BIDSデータセットをZIP化せず、共有ボリューム上に直接展開します。リクエスト元サービスが即座にデータへアクセスできるよう、処理が完了するまでHTTP接続をブロックし、完了後にデータセットへのファイルパスを返します。

**注: 現在の実装には認証・認可機能は含まれていません。**

## 公開API 詳細 (Public API)

### APIエンドポイント

-   `POST /api/v1/experiments/{experiment_id}/export`
    -   BIDSエクスポートのバックグラウンドタスクを開始します。
    -   リクエストボディは不要です。
    -   成功すると即座に `202 Accepted` を返し、タスク情報（`task_id`とステータス確認用URLを含む）を返します。

-   `GET /api/v1/export-tasks/{task_id}`
    -   指定された`task_id`の現在のステータス（`pending`, `processing`, `completed`, `failed`）、進捗（%）、結果へのパスなどを返します。

-   `GET /api/v1/export-tasks/{task_id}/download`
    -   タスクが`completed`状態の場合、MinIOから完成したZIPファイルをストリーミングでダウンロードさせます。

### 処理フロー (Asynchronous)

1.  `POST /.../export`リクエストを受信すると、ユニークな`task_id`を生成し、`export_tasks`テーブルに`pending`状態でレコードを作成します。
2.  FastAPIの`BackgroundTasks`を使い、`create_bids_dataset`関数を`zip_output=True`で非同期に実行します。
3.  クライアントには即座に`task_id`を含む`202 Accepted`レスポンスを返します。
4.  バックグラウンド処理が進行する中、`export_tasks`テーブルの進捗・ステータスが随時更新されます。
5.  処理が完了すると、生成されたZIPファイルがMinIOの`bids_bucket`にアップロードされ、タスクのステータスが`completed`に、`result_file_path`がMinIOのオブジェクト名に更新されます。
6.  クライアントは`GET /.../export-tasks/{task_id}`で進捗をポーリングし、`completed`になったことを確認して`GET /.../download`でファイルをダウンロードします。

## 内部API 詳細 (Internal API)

### APIエンドポイント

-   `POST /internal/v1/create-bids-for-analysis`
    -   `erp_neuro_marketing`サービス専用の同期的（ブロッキング）なエンドポイント。
    -   リクエストボディ: `{"experiment_id": "..."}`
    -   処理が完了すると、`200 OK`と共に、共有ボリューム上のBIDSデータセットへの絶対パスを含むJSON (`{"bids_path": "..."}`) を返します。

### 処理フロー (Synchronous)

1.  `POST /internal/...`リクエストを受信すると、`create_bids_dataset`関数を`zip_output=False`で**同期的**に実行します。
2.  関数はBIDSデータセットを共有ボリューム上の`output_dir`（設定で指定）に直接生成します。
3.  処理が正常に完了すると、生成されたディレクトリへの絶対パスがHTTPレスポンスとして返されます。
4.  エラーが発生した場合は、`404 Not Found`（データ不足など）や`500 Internal Server Error`が返されます。

## BIDS生成ロジック (`create_bids_dataset`)

両APIから呼び出されるコアロジックは以下の通りです。

1.  **データ収集**: DBから`event_correction_status = 'completed'`のセッションと、関連するイベント、刺激定義を取得します。
    - **注:** このステップは、`Processor`サービスによる修正が適用済みの、新しい`raw_data_objects`テーブルスキーマを前提とします。具体的には、`session_id`で生データを検索し、`timestamp_start_ms`でソートする必要があります。
2.  **基本ファイル生成**: `dataset_description.json`, `participants.tsv`を生成します。
3.  **刺激ファイル配置**: `experiment_stimuli`で定義されたメディアファイルをMinIOの`media_bucket`からダウンロードし、BIDSディレクトリ内の`stimuli/`に配置します。
4.  **セッション毎の処理**:
    a.  セッションに紐づく生データオブジェクトをMinIOの`raw_data_bucket`から取得します。
    b.  zstd圧縮または非圧縮のデータを伸長・読み込みします。
    c.  固定オフセットを用いてバイナリデータをパースし、EEGデータを抽出・整形します。
    d.  `mne-python`と`mne-bids`を使い、EEGデータをEDF形式で書き込みます (`..._eeg.edf`)。
    e.  `onset_corrected_us`が設定されたイベントをDBから取得し、生データの開始時刻からの相対オフセットを計算して`..._events.tsv`を生成します。
    f.  `..._eeg.json`（サイドカー）や`..._channels.tsv`に必要な情報を追記・修正します。

---

## スキーマ変更に伴う修正要件 (`create_bids_dataset`ロジック)

新しいデータスキーマに対応するため、BIDS生成の中核をなす`create_bids_dataset`関数は、**データパースとメタデータ抽出のロジックを全面的に書き換える必要があります。**

### 1. バイナリパース処理の書き換え

- **旧処理:** 固定オフセットを前提としたバイナリパース。
- **新処理:** このロジックは**完全に廃止**し、新しいデータスキーマ仕様に従って書き換える必要があります。
  - 各生データオブジェクトを`ヘッダーブロック`と`128個のサンプルデータブロック`の構造としてパースする必要があります。

### 2. BIDSメタデータの動的生成

BIDSファイル (`..._channels.tsv`, `..._eeg.json`) に必要なメタデータは、ハードコードではなく、バイナリのヘッダーブロックから動的に抽出しなければなりません。

- **チャンネル情報 (`..._channels.tsv`):**
  - `ヘッダーブロック`内の`num_channels`と`electrode_config`配列を読み取ります。
  - `electrode_config`をループ処理し、各チャンネルの`name`と`type`を`..._channels.tsv`ファイルに書き出します。

- **サンプリング周波数 (`..._eeg.json`):**
  - `..._eeg.json`サイドカーファイルに必須の`SamplingFrequency`フィールドは、`raw_data_objects`テーブルに記録されている`timestamp_start_ms`と`timestamp_end_ms`から計算する必要があります。
  - **計算式:** `SamplingFrequency = 128 / ((timestamp_end_ms - timestamp_start_ms) / 1000.0)`
  - **注意:** 全てのデータブロックでサンプリング周波数が一定であると仮定しますが、念のため複数のブロックで検証することが望ましいです。

### 3. EEGデータ抽出処理の書き換え

- **旧処理:** 固定オフセットからのEEGデータ読み取り。
- **新処理:** 以下の手順で、全チャンネルの連続した時系列データを再構築する必要があります。
  1.  セッションに属する全ての生データオブジェクトを時系列順にソートします。
  2.  各オブジェクトについて、128個の`サンプルデータブロック`を順番に処理します。
  3.  各サンプルから`signals`配列（`uint16_t`の配列）を抽出します。
  4.  これらの`signals`配列を連結し、チャンネルごとの連続したデータストリームをメモリ上で組み立てます。
  5.  組み立てたデータを`mne-python`が要求するフォーマット（例: `(n_channels, n_samples)`のNumpy配列）に変換し、EDFファイルとして書き込みます。

### 4. イベントファイル (`..._events.tsv`) のタイムスタンプ

- `onset`カラム（イベントの開始時刻）は、BIDS仕様に従い、**そのセッションの最初のEEGサンプルのタイムスタンプを基準とした相対的な秒数**で表現する必要があります。
- `Event Corrector`によって`onset_corrected_us`（マイクロ秒単位の絶対時刻）が計算済みであるため、セッションの最初の`raw_data_objects`の`timestamp_start_ms`を基準として、各イベントの相対的なオフセット（秒単位）を計算し、`onset`カラムに書き込んでください。