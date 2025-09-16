---
service_name: "BIDS Exporter Service"
description: "指定された実験データをBIDS形式に準拠した形でエクスポートするバッチ処理サービス。"
inputs:
  - source: "ERP検出システムなど"
    data_format: "HTTP POST (JSON)"
    schema: "{ experiment_id }"
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "指定された`experiment_id`に属する全てのセッションメタデータ (`sessions`)、実績イベントログ (`session_events`)、および関連する刺激定義 (`experiment_stimuli`)"
  - source: "MinIO"
    data_format: "Object GET"
    schema: "セッションに対応する圧縮済み生データオブジェクト群、および刺激ファイル群"
outputs:
  - target: "ERP検出システムなど"
    data_format: "BIDS"
    schema: "BIDS形式のディレクトリ構造を持つデータセット"
---

## 概要

`BIDS Exporter`は、オンデマンドで起動されるバッチ処理サービスです。指定された実験IDに紐づく全てのデータを収集し、BIDS標準形式にパッケージングして提供します。

## 詳細

- **責務**: **「保存済みの一次データと全てのメタデータを読み出し、解釈・整形し、標準化された共有可能な形式に変換・出力すること」**。

- **処理フロー**:
    1.  API経由で`experiment_id`を受け付ける。
    2.  PostgreSQLに問い合わせ、以下の情報を取得する:
        -   `experiment_id`に属する全てのセッション情報 (`sessions`テーブル)。
        -   各セッションに紐づく**実績イベントログ** (`session_events`テーブル)。
        -   実験に登録されている**刺激の定義情報** (`experiment_stimuli`テーブル)。
        -   各セッションに関連する生データオブジェクトのID (`session_object_links`経由)。
    3.  MinIOから、関連する全ての**圧縮済み生データオブジェクト**と、`experiment_stimuli`で参照されている**刺激ファイル（画像等）**をダウンロードする。
    4.  生データを時系列に沿って結合し、Zstandardで解凍する。
    5.  MNE-Pythonの`Raw`オブジェクトなどを生成する。
    6.  **`session_events`テーブルの情報（onset, durationなど）を基に、BIDSの`events.tsv`ファイルを生成する。** `trial_type`などの詳細なカラムもこの情報から作成する。
    7.  ダウンロードした刺激ファイルを`stimuli`ディレクトリに配置するなど、BIDSの仕様に従ってデータセットを構築する。
    8.  `mne_bids.write_raw_bids`関数などを用いて、完全なBIDS形式のディレクトリ構造とメタデータファイルを生成する。
    9.  生成されたディレクトリ全体をZIPファイルに圧縮し、ユーザーに提供する。
