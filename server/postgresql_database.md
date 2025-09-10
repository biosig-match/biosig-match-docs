---
service_name: "PostgreSQL Database"
description: "全てのメタデータを管理する、信頼性の高いリレーショナルデータベース。"
inputs:
  - source: "Session Managerサービス"
    data_format: "SQL INSERT/UPDATE"
    schema: "実験、セッション情報"
  - source: "（データ紐付けワーカー）"
    data_format: "SQL UPDATE"
    schema: "セッションとオブジェクトIDの関連付け"
outputs:
  - target: "BIDS Exporterサービス, Session Managerサービス"
    data_format: "SQL SELECT"
    schema: "各種メタデータの読み出し"
---

## 概要

PostgreSQL は、本システムにおける**「信頼できる唯一の情報源（Single Source of Truth）」**として、全ての構造化されたメタデータを管理します。実験、セッション、ユーザー、そしてそれらの関係性といった、高速な検索とトランザクションの整合性が求められる情報を格納します。

## 詳細

- **役割**: **「構造化されたメタデータの管理と、データ間の一貫性の保証」**。
- **主なテーブルスキーマ**:

  - **`experiments` テーブル**:

    - `experiment_id` (UUID, PK): サーバーが発行する一意な実験 ID。
    - `name` (VARCHAR): 実験名。
    - `description` (TEXT): 実験の詳細。
    - `created_at` (TIMESTAMPTZ): 作成日時。

  - **`sessions` テーブル**:
    - `session_id` (VARCHAR, PK): クライアントが生成する一意なセッション ID (`user-start-end`)。
    - `user_id` (VARCHAR): セッションを実行したユーザーの ID。
    - `experiment_id` (UUID, FK to experiments): このセッションが属する実験の ID。
    - `start_time` (TIMESTAMPTZ): セッション開始時刻(UTC)。
    - `end_time` (TIMESTAMPTZ): セッション終了時刻(UTC)。
    - `session_type` (VARCHAR): 'calibration' または 'main'。
    - `calibration_for_session_id` (VARCHAR, FK to sessions): このセッションがキャリブレーションである場合、対象となる本実験セッションの ID。
    - `link_status` (VARCHAR): データ紐付けジョブの状況 ('pending', 'processing', 'completed', 'failed')。

- **背景**:
  - **ACID 特性**: 実験やセッションの登録・更新は、原子性(Atomicity)、一貫性(Consistency)、独立性(Isolation)、永続性(Durability)が保証されるべき操作です。PostgreSQL のようなリレーショナルデータベースは、これらの ACID 特性を保証するトランザクション機能を提供します。
  - **強力なクエリ能力**: 「ユーザー A の、実験 B に属する、全てのキャリブレーションセッションをリストアップする」といった複雑な条件でのデータ検索が、SQL を用いて高速かつ柔軟に行えます。これはオブジェクトストレージ単体では困難な操作です。
