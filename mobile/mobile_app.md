---
service_name: "Smartphone App"
description: "ユーザーインターフェースを提供し、ファームウェアとサーバー群を繋ぐ中継ハブ。実験設計、セッション管理、データ中継の役割を担う。"

inputs:
  - source: "ファームウェア (BLE)"
    data_format: "BLE Notify (Compressed Sensor Data)"
    schema: "Zstandard圧縮されたバイナリデータ"
  - source: "ユーザー"
    data_format: "UI操作"
    schema: "ログイン、実験の作成/選択/設計、セッションモード選択、セッション開始/終了など"
  - source: "内蔵マイク・カメラ"
    data_format: "音声(WAVなど), 画像(JPEGなど)"
    schema: "セッション中に定期的にキャプチャされるメディアデータ"

outputs:
  - target: "Collectorサービス"
    data_format: "HTTP POST (JSON)"
    schema: "エンドポイント `/api/v1/data`: { user_id, payload_base64 }"
  - target: "Collectorサービス"
    data_format: "HTTP POST (Multipart/form-data)"
    schema: "エンドポイント `/api/v1/media`: { user_id, session_id } を含むメディアファイル"
  - target: "Session Managerサービス"
    data_format: "HTTP POST/GET (JSON), HTTP POST (Multipart/form-data)"
    schema: "実験作成リクエスト、刺激アセット登録、セッション終了通知"
---

## 概要

本アプリは、ユーザーが実験を「設計」し、セッションを「実行・管理」するためのUIを提供します。BLE経由でセンサーデータを常時転送する一方、実験のワークフローに応じて刺激アセットの登録や実績ログのアップロードを行います。

## 詳細

### 実験・セッション管理

- **責務**: `Session Manager`と連携し、実験の設計からセッション完了までのライフサイクル全体を管理する。
- **ワークフロー**:
  1. **実験作成/選択**: ユーザーは実験を作成または選択する。
  2. **実験設計 (All-in-Oneモード)**:
     - ユーザーはアプリ内の「実験設計画面」で、刺激を定義したCSVと、それに対応する画像ファイル群を`/api/v1/experiments/{id}/stimuli`へアップロードする。
  3. **セッションモード選択**:
     - ユーザーが「セッション開始」をタップすると、「アプリで刺激を提示（All-in-One）」か「外部アプリで刺激を提示（Hybrid）」かを選択するダイアログが表示される。
  4. **セッション開始**:
     - **All-in-Oneモード**: アプリが事前に登録された刺激を提示し、同時に脳波を記録。イベントログはアプリ内部で自動生成される。
     - **Hybridモード**: アプリは脳波の記録のみを開始。ユーザーはPC上のPsychoPyなどで刺激を提示する。
  5. **セッション終了**: ユーザーが計測を終了すると、セッション終了画面へ遷移する。
  6. **完了処理**:
     - **All-in-Oneモード**: アプリが自動生成したイベントログとセッションメタデータを`/api/v1/sessions/end`へ送信する。
     - **Hybridモード**: ユーザーは**PsychoPyなどが出力したイベントログCSV**をファイル選択し、セッションメタデータと共に`/api/v1/sessions/end`へ送信する。
