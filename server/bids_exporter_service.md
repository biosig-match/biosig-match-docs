---
service_name: "BIDS Exporter Service"
description: "指定された実験データをBIDS形式に準拠した形でエクスポートするバッチ処理サービス。"
inputs:
  - source: "ERP検出システム"
    data_format: "HTTP POST (JSON)"
    schema: "{ experiment_id }"
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: "指定された`experiment_id`に属する全てのセッションメタデータ"
  - source: "MinIO"
    data_format: "Object GET"
    schema: "セッションに対応する圧縮済み生データオブジェクト群"
outputs:
  - target: "ERP検出システム"
    data_format: "BIDS"
    schema: "BIDS形式のディレクトリ構造を持つデータセット"
---

## 概要

`BIDS Exporter`は、オンデマンドで起動されるバッチ処理サービスです。ユーザーからエクスポート要求を受けると、指定された実験 ID に紐づく全てのセッションデータを PostgreSQL と MinIO から収集し、MNE-BIDS ライブラリなどを用いて BIDS 標準形式のディレクトリ構造にパッケージングし、ダウンロード可能な ZIP ファイルとして提供します。

## 詳細

- **責務**: **「保存済みの一次データを読み出し、解釈・整形し、標準化された共有可能な形式に変換・出力すること」**。

- **処理フロー**:
    1.  API 経由で`experiment_id`をキーとしてエクスポート要求を受け付ける。
    2.  PostgreSQL に問い合わせ、指定された`experiment_id`に属する全てのセッション情報（`session_id`, `user_id`, 開始/終了時刻など）と、それに関連するデータオブジェクトの ID (`session_object_links`経由) を取得する。
    3.   各データオブジェクト ID に基づき、MinIO から関連する全ての**圧縮済み生データオブジェクト**をダウンロードする。
    4.   ダウンロードしたデータを**時系列に沿って結合し、Zstandard で解凍する**。
    5.   解凍後のバイナリデータから EEG、IMU などのデータを分離・整形し、MNE-Python の`Raw`オブジェクトなどを生成する。
    6.   イベント情報などを`Annotations`として付与する。
    7.  `mne_bids.write_raw_bids`関数などを用いて、BIDS 形式のディレクトリ構造とメタデータファイルを生成する。
    8.   生成されたディレクトリ全体を ZIP ファイルに圧縮し、ユーザーにダウンロードリンクを提供する。

- **背景**: BIDS 形式への変換は、大量のデータをディスクに読み出し、多くの CPU リソースを消費する、時間のかかる処理です。本サービスは非同期のバックグラウンドジョブとして実行されるため、**エクスポート処理中のデータ解凍や分離による負荷増大は許容範囲内**と判断されます。この設計により、データ収集ライン（`Processor`）の責務を可能な限り単純化し、データの完全性を保証するというシステム全体の思想を優先しています。
