---
service_name: "Realtime Analyzer Service"
description: "生のセンサーデータをリアルタイムに解析し、脳波指標（PSD、Coherence）を算出してAPI経由で提供するサービス。"

inputs:
  - source: "RabbitMQ (bound to raw_data_exchange)"
    data_format: "AMQP Message"
    schema: |
      Exchange: raw_data_exchange (fanout)
      Body: Zstandard-compressed binary data
      Headers: { "user_id": "string" }

outputs:
  - target: "Frontend Client (e.g., Smartphone App)"
    data_format: "HTTP GET (JSON)"
    schema: |
      // GET /api/v1/users/{user_id}/analysis
      {
        "psd_image": "string (base64-encoded PNG)",
        "coherence_image": "string (base64-encoded PNG)",
        "timestamp": "ISO8601 string"
      }
---

## 概要

`Realtime Analyzer`は、`Processor`サービスと並行して`raw_data_exchange`から生のセンサーデータを受け取る、リアルタイム解析に特化したサービスです。データはユーザーごとにメモリ上のリングバッファに蓄積され、バックグラウンドで定期的に解析が実行されます。解析結果（PSDとCoherenceのプロット画像）はメモリ内に保持され、クライアントはAPIを介して最新の解析結果をいつでも取得できます。

---

## スキーマ変更に伴う修正要件

新しいデータスキーマに対応するため、`Realtime Analyzer`のデータ受信・解析ロジックは、**特にデータパース部分を全面的に書き換える必要があります。**

### 1. AMQPメッセージの入力仕様変更

`Collector`から受け取るAMQPメッセージのヘッダーに、`session_id`, `device_id`, `timestamp_start_ms`, `timestamp_end_ms`が追加されます。特にタイムスタンプはサンプリング周波数の計算に必須です。

### 2. バイナリパースとEEGデータ抽出ロジックの書き換え

- **旧処理:** 旧仕様のバイナリからEEGサンプルを抽出していました。
- **新処理:** このロジックは**完全に廃止**し、新しいデータスキーマ仕様に従って書き換える必要があります。
  1.  zstd伸長後、受信したバイナリを`ヘッダーブロック`と`128個のサンプルデータブロック`としてパースします。
  2.  128個の各サンプルデータブロックから`signals`配列を抽出します。
  3.  抽出した`signals`をメモリ上のリングバッファ（Numpy配列）に追加します。

### 3. MNE-Python用メタデータの動的生成

MNEライブラリで正しく解析を行うためには、`mne.Info`オブジェクトに正確なメタデータを渡す必要があります。これらの情報は、受信したデータから動的に生成しなければなりません。

- **チャンネル情報:**
  - `ヘッダーブロック`内の`num_channels`と`electrode_config`配列を読み取ります。
  - `electrode_config`からチャンネル名のリストを生成し、`mne.Info`オブジェクトの作成時に渡します。

- **サンプリング周波数:**
  - `mne.Info`オブジェクトに必須のサンプリング周波数（`sfreq`）は、AMQPメッセージヘッダーの`timestamp_start_ms`と`timestamp_end_ms`から計算する必要があります。
  - **計算式:** `sfreq = 128 / ((timestamp_end_ms - timestamp_start_ms) / 1000.0)`
  - **注意:** この計算はデータを受信するたびに毎回実行し、`mne.Info`オブジェクトを生成または更新する必要があります。サンプリング周波数がセッション中に変動する可能性も考慮に入れるべきです。

### 4. 解析の単位

- 新しいヘッダーに含まれる`session_id`を利用して、セッションの切れ目で解析バッファをクリアする、といった改善が考えられます。

---

## 詳細

-   **責務**: **「準リアルタイムでのデータ解析と、その結果の即時提供」**。データの永続化には一切関与しません。
-   **アーキテクチャ**: 本サービスはFlaskアプリケーションとして動作し、内部で2つのデーモンスレッド（RabbitMQコンシューマ、解析ワーカー）を並行して実行します。データと結果は全てメモリ上で管理され、スレッドセーフなアクセスが保証されています。

### 処理フロー

1.  **データ受信 (RabbitMQ Consumer Thread)**:
    a.  起動時に`raw_data_exchange`に接続し、サービスインスタンスごとに一時的・排他的なキューをバインドします。これにより、`Collector`が発行する全ての生データパケットのコピーを受信します。
    b.  メッセージを受信すると、zstdでペイロードを伸長し、バイナリデータからEEGサンプルを抽出します。
    c.  メッセージヘッダーの`user_id`をキーとして、メモリ上の`user_data_buffers`辞書にある該当ユーザーのデータバッファ（Numpy配列）に新しいサンプルを追加します。
    d.  メモリ枯渇を防ぐため、各ユーザーのバッファは最大60秒分のサンプル数に制限され、上限を超えると古いデータから破棄されます。

2.  **定周期解析 (Analysis Worker Thread)**:
    a.  設定された間隔（`analysis_interval_seconds`）で定期的に起動するループ処理を実行します。
    b.  全てのユーザーバッファをチェックし、解析に必要なサンプル数（`analysis_window_seconds`分）が溜まっているものを対象とします。
    c.  MNE-Pythonライブラリを用いて、バッファの末尾から取得した最新のデータチャンクに対して以下の解析を実行します。
        -   **パワースペクトル密度 (PSD)**: `compute_psd`で計算し、結果をグラフ（`matplotlib.Figure`）としてプロットします。
        -   **コヒーレンス (Coherence)**: 8-13Hz（α帯）の周波数帯における`spectral_connectivity_epochs`を計算し、結果をコネクティビティサークルとしてプロットします。
    d.  生成された2つのグラフをPNG形式の画像に変換し、さらにBase64エンコードして文字列化します。
    e.  `latest_analysis_results`辞書に、`user_id`をキーとして、2つの画像文字列と現在時刻のタイムスタンプを保存します。

### APIエンドポイント

-   `GET /api/v1/users/<user_id>/analysis`
    -   **目的**: 指定されたユーザーの最新の解析結果を取得します。
    -   **処理**: メモリ上の`latest_analysis_results`辞書から`user_id`に対応するデータを検索します。
    -   **レスポンス**:
        -   結果が存在する場合: `200 OK`と共に、`psd_image`, `coherence_image`, `timestamp`を含むJSONオブジェクトを返します。
        -   結果がまだ存在しない場合: `202 Accepted`と共に、解析がまだ利用できない旨のステータスメッセージを返します。