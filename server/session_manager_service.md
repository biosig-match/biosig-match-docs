---
service_name: "Session Manager Service"
description: "実験とセッションのメタデータを管理し、ライフサイクルを司るサービス。"
inputs:
  - source: "Smartphone App"
    data_format: "HTTP POST/GET (JSON)"
    schema: "実験作成リクエスト、セッション終了通知など"
outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`experiments`テーブル, `sessions`テーブルへの書き込み"
  - target: "Async Task Queue (DataLinker)"
    data_format: "Job"
    schema: "データ紐付け処理のタスク"
---

## 概要

`Session Manager`は、BIDS の階層構造（実験 > セッション）に準拠したメタデータの管理を行います。実験の作成、セッションの登録といったライフサイクル管理 API を提供し、セッション終了時には、記録された生データとセッション情報を紐付けるための非同期ジョブを起動します。

## 詳細

- **責務**: **「実験とセッションという『意味』の管理」**。
- **API エンドポイント**:
  - `POST /api/v1/experiments`: 新規実験を作成し、一意な`experiment_id`を発行。
  - `GET /api/v1/experiments`: 既存の実験リストを取得。
  - `POST /api/v1/sessions/end`: セッション終了時にスマホアプリから呼び出され、セッション情報（`session_id`, `user_id`, `start_time`, `end_time`など）を PostgreSQL に登録する。
- **データ紐付け処理**:
  - セッション終了情報を受け取ると、`Session Manager`は**それ自体では重い検索処理を行いません**。
  - 代わりに、セッションの時間範囲などの情報を含む「データ紐付けジョブ」を、Celery や BullMQ のような非同期タスクキューに投入します。
  - 実際に MinIO 内を検索する処理は、独立したワーカープロセスが非同期に実行します。
- **背景**: ユーザーのアクション（セッション終了）に対するレスポンスは即座に返すべきです。数秒〜数分かかる可能性のあるデータ検索処理を API リクエストの処理と同時に行うと、ユーザー体験を著しく損ないます。処理を非同期化することで、API の応答性を保ちつつ、重い処理をサーバーの都合の良いタイミングで確実に実行できます。また、PostgreSQL でセッションと実験のメタデータを一元管理することで、データ全体の構造的な整合性を保ちます。
