---
service_name: "MinIO"
description: "全ての生データ（EEG/IMU, 画像, 音声など）を格納する、スケーラブルなストレージ基盤。"
inputs:
  - source: "Processorサービス"
    data_format: "Zstandard圧縮されたバイナリ"
    schema: "EEG/IMUデータ"
  - source: "スマートフォンアプリ"
    data_format: "画像/音声ファイル"
    schema: "JPEG, WAVなど"
outputs:
  - target: "BIDS Exporterサービス"
    data_format: "同上"
    schema: "リクエストに応じてオブジェクトを読み出し"
---

## 概要

MinIO は、本システムにおける一次データ（raw data）の格納庫です。GB 単価が安く、高い拡張性と可用性を持つオブジェクトストレージは、日々増え続ける大容量の生体データを保存するのに最適です。

## 詳細

- **役割**: **「変更されない大容量データの効率的な保管」**。
- **格納データ**:
  - `Processor`によって整形・圧縮された EEG/IMU データ
  - スマートフォンからアップロードされた画像、音声ファイル
- **命名規則（ディレクトリ構造）**:
  - **目的**: パス自体がメタデータとして機能し、効率的な検索を可能にするため。
  - **EEG/IMU**: `eeg/{user_id}/start_ms={start_unix_ms}/end_ms={end_unix_ms}_{uuid}.zst`
  - **メディア**: `media/{user_id}/{session_id}/{timestamp_ms}_{filename}.jpg`
- **背景**:
  - **DB-Offloading**: 生データのような巨大なバイナリデータを PostgreSQL に保存すると、バックアップ時間の増大、パフォーマンスの低下、コストの増加など多くの問題を引き起こします。データ本体をオブジェクトストレージに逃がし、DB ではその場所を示す ID（オブジェクトキー）やメタデータのみを管理するのが現代的なアーキテクチャの定石です。
  - **不変性(Immutability)**: 一度書き込まれた生データは、原則として変更・削除されません。このような Write-Once-Read-Many (WORM)の特性を持つデータは、オブジェクトストレージの得意分野です。
