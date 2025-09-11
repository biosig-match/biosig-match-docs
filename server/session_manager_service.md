---
service_name: "Session Manager Service"
description: "実験とセッションのメタデータ、およびERPタスク等のイベントデータを管理し、ライフサイクルを司るサービス。"

inputs:
  - source: "Smartphone App"
    data_format: "HTTP POST/GET (JSON)"
    schema: "実験作成・一覧取得リクエスト"
  - source: "Smartphone App"
    data_format: "HTTP POST (Multipart/form-data)"
    schema: "セッション終了通知。JSONパートにセッションメタデータ、ファイルパートにイベントリスト(CSV)を含む。"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`experiments`テーブル, `sessions`テーブル, `events`テーブルへの書き込み"
  - target: "Async Task Queue (DataLinker)"
    data_format: "Job"
    schema: "データ紐付け処理のタスク"
---

## 概要

`Session Manager`は、BIDS の階層構造（実験 > セッション）に準拠したメタデータの管理を行います。ユーザーによる実験の新規作成や既存実験への参加、セッションの登録といったライフサイクル管理 API を提供します。セッション終了時には、セッション情報とオプションのイベントリストをアトミックに受け付け、DB を更新すると共に、データ紐付けジョブを起動します。

## 詳細

- **責務**: **「実験とセッションという『意味』の管理」**および、**「セッションに紐づくイベントの管理」**。

- **API エンドポイント**:

  - `POST /api/v1/experiments`: 新規実験を作成し、一意な`experiment_id`を発行。
  - `GET /api/v1/experiments`: 参加可能な既存の実験リストを取得。
  - `POST /api/v1/sessions/end`: セッション終了時にスマホアプリから呼び出される。**セッション情報とイベント CSV をまとめて受け付ける。**
    - **Request Body (Multipart/form-data)**:
      - `metadata` (part): セッション情報を含む JSON 文字列 (`{ session_id, user_id, experiment_id, start_time, end_time, session_type }`)
      - `events_file` (part, optional): イベント情報を含む CSV ファイル。
    - **処理**: 受け取った情報で`sessions`テーブル等を更新し、データ紐付けジョブを投入する。

- **データ紐付け処理**:

  - セッション終了情報を受け取ると、`Session Manager`はセッションの時間範囲などの情報を含む「データ紐付けジョブ」を非同期タスクキューに投入します。

- **背景**: セッションのメタデータとイベントリストは不可分な情報であるため、単一のエンドポイントでアトミックに受け付けることでデータの一貫性を保証します。
