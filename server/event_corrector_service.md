---
service_name: "Event Corrector Service"
description: "生データ内の高精度トリガ信号とイベントログを照合し、ERP解析に不可欠なマイクロ秒精度のイベント時刻を算出する、計算集約型の非同期バックエンドサービス。"

inputs:
  - source: "DataLinker Service (via RabbitMQ: event_correction_queue)"
    data_format: "AMQP Message (JSON)"
    schema: |
      {
        "session_id": "user-abcdef-1726000000000"
      }
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "指定された`session_id`に紐づく`session_events`および`session_object_links`の全レコード"
  - source: "MinIO"
    data_format: "Object GET"
    schema: "`session_object_links`経由で特定された、セッションに対応する圧縮済み生データオブジェクト群"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL UPDATE"
    schema: "`session_events`テーブルの`onset_corrected_us`カラムへの書き込み、および`sessions`テーブルの`event_correction_status`の更新"
---

## 概要

`Event Corrector Service`は、`DataLinker`による基本的なデータ紐付けが完了した後に起動される、専門的なバッチ処理ワーカーです。その唯一の責務は、**PsychoPyなどが出力したイベントログの時刻 (`onset`) を、センサーデータ内に記録されている物理的なトリガ信号の発生時刻（マイクロ秒精度）と照合し、イベントの発生時刻をマイコンの高精度な内部クロックに完全に同期させること**です。

## 詳細

### 責務 (Responsibilities)

- **「生データとイベントログのシーケンスを照合し、各イベントの発生時刻を、ネットワーク遅延などの外的要因から完全に独立した、デバイスの内部時間軸へと補正すること」**

このサービスは、システムのデータ精度を保証する最後の砦であり、特にERP（事象関連電位）のようなミリ秒単位の精度が求められる脳波解析において、不可欠な役割を担います。

### 処理フロー (Processing Flow)

1.  `event_correction_queue`から`session_id`を含むジョブを一つ取り出します。
2.  対象セッションの`sessions.event_correction_status`を`'processing'`に更新します。
3.  **データベースからメタデータを収集**:
    - `session_id`をキーに、`session_events`テーブルから全てのイベント（`trial_type`, `onset`など）のシーケンスを取得します。
    - `session_object_links`テーブルから、このセッションに関連する全ての生データオブジェクトの`object_id`を取得します。
4.  **MinIOから生データをダウンロード**:
    - 取得した`object_id`のリストに基づき、MinIOから全ての圧縮済み生データ（`.zst`ファイル）をダウンロードします。
5.  **データの解凍とトリガ抽出**:
    - ダウンロードしたオブジェクトを時系列順に連結し、Zstandardで解凍します。
    - 解凍後のバイナリデータを`SensorData`構造体に従ってパースし、`trigger`が`1`になっている箇所の**高精度デバイスタイムスタンプ (`timestamp_us`)** のリストを時系列で抽出します。
6.  **シーケンスマッチング**:
    - `session_events`のシーケンスと、抽出したトリガのタイムスタンプリストを照合するアルゴリズムを実行します。（例：イベント数とトリガ数が一致するか、イベント間の時間差とトリガ間の時間差のパターンが類似しているか、など）
7.  **データベースの更新 (トランザクション内)**:
    - マッチングに成功した場合、各`session_events`レコードに対応するトリガの`timestamp_us`を、新しく設けられた`onset_corrected_us`カラムに`UPDATE`します。
    - `sessions.event_correction_status`を`'completed'`に更新します。
8.  エラーが発生した場合はトランザクションを`ROLLBACK`し、ステータスを`'failed'`に更新します。

### 背景 (Background)

- **データ精度の最大化**: PsychoPyがイベントログに記録する`onset`は、PCのOSやネットワークの遅延（ジッター）の影響を受け、数ミリ秒〜数十ミリ秒の誤差を含む可能性があります。ERP解析においてこの誤差は致命的です。本サービスは、イベントの発生時刻を、誤差要因のないセンサー自身の時間軸にアンカーすることで、この問題を根本的に解決します。
- **重処理の分離**: MinIOからの大容量ダウンロード、データ解凍、バイナリパースは非常に計算コストの高い処理です。これを`DataLinker`から分離することで、`DataLinker`は軽量なメタデータ操作に集中でき、システム全体の応答性と安定性が向上します。
