---
service_name: "Auth Manager Service"
description: "実験へのアクセス権（誰が、どの実験に、何をできるか）を一元管理する、セキュリティの要となるサービス。"

inputs:
  - source: "Internal Services (e.g., ERP Neuro-Marketing)"
    data_format: "HTTP POST (JSON)"
    schema: "`POST /api/v1/auth/check` with body `{"user_id", "experiment_id", "required_role"}`"
  - source: "Frontend Clients (e.g., Smartphone App)"
    data_format: "HTTP POST/GET/PUT (JSON)"
    schema: "`/api/v1/auth/experiments/...` エンドポイント群へのリクエスト"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE/SELECT/DELETE"
    schema: "`experiments` (read-only for password hash) and `experiment_participants` (read/write) tables"
  - target: "Requesting Service/Client"
    data_format: "HTTP Response (JSON)"
    schema: "`{"authorized": boolean}` or data payload/error message"
---

## 概要

`Auth Manager`は、本システムにおける全ての**認可 (Authorization)** を司る専用サービスです。「実験」という閉じられたリソースへのアクセス制御に特化し、誰が実験のオーナーで、誰が参加者なのか、といった情報を`experiment_participants`テーブルで一元管理します。他のサービスは、権限が必要な操作を行う前に、必ず本サービスの内部APIに権限の有無を問い合わせる必要があります。

## 詳細

-   **責務**: **「ユーザーと実験の関連付け、およびロール（役割）に基づいたアクセス権の判定」**。
-   **ロール**: `owner`と`participant`の2種類が存在します。
-   **認証 (Authentication)**: 本サービスは**認可**に特化しており、ユーザー自体の認証（ログインなど）は行いません。リクエスト元が誰であるかは、HTTPヘッダーなどを通じて信頼された情報として渡されることを前提とします。

## APIエンドポイント

全てのパスは `/api/v1/auth` をプレフィックスとします。

### `POST /experiments/:experiment_id/join`

ユーザーが実験に参加するために使用します。

-   **リクエストボディ**: `{"user_id": "string", "password": "string (optional)"}`
-   **処理フロー**:
    1.  `experiments`テーブルを検索し、対象の実験にパスワード (`password_hash`) が設定されているか確認します。
    2.  パスワードが設定されている場合、リクエストボディの`password`を`Bun.password.verify`で検証します。パスワードが不一致または未提供の場合は`401 Unauthorized`を返します。
    3.  `experiment_participants`テーブルに、`user_id`と`experiment_id`を`'participant'`ロールで`INSERT`します。
    4.  `ON CONFLICT`句により、ユーザーが既に存在する場合は何もせず、成功として扱います。
    5.  成功した場合、`201 Created`を返します。

### `GET /experiments/:experiment_id/participants`

実験の参加者一覧を取得します。**オーナー権限が必要**です。

-   **ヘッダー**: `X-User-Id` (リクエスト元のユーザーID) が**必須**です。
-   **処理フロー**:
    1.  `X-User-Id`ヘッダーのユーザーが、対象実験の`'owner'`であるかを確認します。
    2.  オーナーでない場合は`403 Forbidden`を返します。
    3.  オーナーである場合は、その実験の全参加者の`user_id`, `role`, `joined_at`のリストを返します。

### `PUT /experiments/:experiment_id/participants/:user_id`

実験参加者のロールを変更します。**オーナー権限が必要**です。

-   **ヘッダー**: `X-User-Id` (リクエスト元のユーザーID) が**必須**です。
-   **リクエストボディ**: `{"role": "owner" | "participant"}`
-   **処理フロー**:
    1.  `X-User-Id`ヘッダーのユーザーが、対象実験の`'owner'`であることを確認します。
    2.  オーナーでない場合は`403 Forbidden`を返します。
    3.  オーナーである場合は、パスパラメータで指定された`:user_id`を持つ参加者の`role`を更新します。
    4.  成功した場合、更新後の参加者情報を返します。

### `POST /check` (内部API)

他の内部サービスが権限を確認するための、最重要エンドポイントです。

-   **リクエストボディ**: `{"user_id": "string", "experiment_id": "string", "required_role": "owner" | "participant"}`
-   **処理フロー**:
    1.  リクエストボディの`user_id`が、`experiment_id`に対して要求されたロール (`required_role`) を満たしているか、`experiment_participants`テーブルを検索して確認します。
    2.  **権限ロジックの階層性**: `required_role`が`'participant'`の場合、ユーザーの実際のロールが`'participant'`または`'owner'`であれば許可されます。`required_role`が`'owner'`の場合は、実際のロールが`'owner'`でなければ許可されません。
    3.  結果を`{"authorized": true}`または`{"authorized": false}`の形式で返します。