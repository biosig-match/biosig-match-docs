---
service_name: "Session Manager Service"
description: "実験のライフサイクル全体を管理するサービス。実験の定義、刺激アセット（画像、イベントリスト）の登録、セッション結果の記録を担う。"

inputs:
  - source: "Smartphone App"
    data_format: "HTTP POST/GET (JSON)"
    schema: "実験作成・一覧取得リクエスト"
  - source: "Smartphone App"
    data_format: "HTTP POST (Multipart/form-data)"
    schema: "エンドポイント `/api/v1/experiments/{experiment_id}/stimuli`: 実験で使用する刺激アセット（イベントリストCSVと全ての画像ファイル）の一括アップロード。"
  - source: "Smartphone App"
    data_format: "HTTP POST (Multipart/form-data)"
    schema: "エンドポイント `/api/v1/sessions/end`: セッション終了通知。JSONパートにセッションメタデータ、ファイルパートに実績イベントログ(CSV)を含む。"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`experiments`, `sessions`, `experiment_stimuli`, `session_events`テーブルへの書き込み"
  - target: "Async Task Queue (DataLinker)"
    data_format: "Job"
    schema: "データ紐付け処理のタスク"
---

## 概要

`Session Manager`は、実験の「設計」から「実施」、「記録」までのライフサイクル全体を管理する司令塔です。ユーザーはまず実験を作成し、**その実験で使用する全ての刺激アセット（イベントリストCSVと画像ファイル群）を本サービスに登録します（実験の「計画」）。** この実験の参加者は、登録されたイベントリストCSVと画像ファイル群をもとに erp 検出タスクを行うことになります。セッション終了時には、どの刺激がいつ提示されたかという実行結果（「実績」）を受け取り、DBを更新すると共に、後続のデータ紐付けジョブを起動します。

## 詳細

- **責務**: **「実験という『意味』の定義と、それに紐づくアセットの管理」**、および**「実行されたセッション結果の記録」**。

- **API エンドポイント**:

  - `POST /api/v1/experiments`: 新規実験を作成。
  - `GET /api/v1/experiments`: 既存の実験リストを取得。
  - `POST /api/v1/experiments/{experiment_id}/stimuli`: 実験の「計画」を登録する最重要エンドポイント。
    - **用途**: 実験設計時に使用。
    - **Request Body (Multipart/form-data)**:
      - `stimuli_definition_csv` (part): 刺激の定義ファイル。アプリでは UI で刺激の提示順を決定できるため、決定された刺激順をアプリ内でcsvファイルとして生成する。全実験参加者に強制したい刺激の提示順があればこれによって決定する。提示順決定時にランダムな提示順が選択された場合、このファイルは順番の意味を持たず、単なる提示ファイルリストとして DB に登録される。
        - **CSV Schema (例)**: `trial_type,file_name,description(optional)`
        - trial_type は、キャリブレーション時のみ target_or_nontarget を 1 or 0 で示す。
      - `stimulus_files` (part, multiple): CSVの`file_name`列に記載された全ての画像・音声ファイル。
    - **処理フロー**:
      1. **トランザクション開始**し、整合性を保証。
      2. **CSVパース**し、必要な刺激ファイル名と実験条件（`trial_type`）のリストを作成。
      3. **アセット検証**: アップロードされた`stimulus_files`とCSV記載の`file_name`を照合し、**過不足がないか厳密にチェックする。**
      4. **ファイル永続化**: 各刺激ファイルをMinIOへアップロード、`object_id`を取得。将来的には専用のサービス（新規実装の必要あり）に責務を分散できるとよい。
      5. **DB登録**: CSVの各行について、`experiment_id`や取得した`object_id`を`experiment_stimuli`テーブルに`INSERT`する。
      6. **トランザクション完了**。

  - **`POST /api/v1/sessions/end` (UPDATED)**: **セッションの「実績」を登録するエンドポイント。**
    - **用途**: 全てのセッションタイプ（All-in-One, Hybrid）の終了時に呼び出される。
    - **Request Body (Multipart/form-data)**:
      - `metadata` (part): セッション情報を含むJSON文字列。
      - `events_log_csv` (part, optional): イベント実績ログ。
        - **CSV Schema (例)**: `trial_type,file_name,description,onset(optional),duration(optional)`
        - PsychoPy のイベントリストの csv スキーマに忠実に合わせる。
        - **備考**: PsychoPy等と連携する「Hybridモード」では必須。アプリ完結の「All-in-Oneモード」ではアプリが内部生成して送信。
    - **処理**:
      1. `metadata`で`sessions`テーブルを更新。
      2. `events_log_csv`が存在すればパースし、各行を`session_events`テーブルに`INSERT`する。
      3. データ紐付けジョブを`DataLinker`のために非同期タスクキューに投入する。
