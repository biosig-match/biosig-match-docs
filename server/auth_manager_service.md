---
service_name: "Auth Manager Service"
component_type: "service"
description: "実験への参加権限とロールを統合管理し、他サービスからの認可問い合わせに対して判定結果を返す。"
inputs:
  - source: "Frontend / 内部HTTPクライアント"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/auth/experiments/:experiment_id/join
      Body:
        user_id: string
        password?: string
  - source: "Session Manager Service"
    data_format: "HTTP POST (JSON)"
    schema: |
      POST /api/v1/auth/check
      Body:
        user_id: string
        experiment_id: uuid
        required_role: 'owner' | 'participant'
  - source: "PostgreSQL"
    data_format: "SQL SELECT"
    schema: |
      - experiments(password_hash)
      - experiment_participants(role, joined_at)
outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: |
      - INSERT experiment_participants(experiment_id, user_id, role)
      - UPDATE experiment_participants SET role = $1 WHERE experiment_id = $2 AND user_id = $3
  - target: "呼び出し元クライアント"
    data_format: "HTTP JSON"
    schema: |
      成功レスポンス:
        - 参加登録: {"message": "Successfully joined experiment"}
        - 参加者一覧: [{"user_id","role","joined_at"}]
        - 権限判定: {"authorized": boolean}
      エラーレスポンス: {"error": string}
---

## 概要

`Auth Manager Service` は、`experiment_participants` テーブルを正としつつ、実験単位でのアクセス制御を提供します。参照系エンドポイントでのみロールを確認し、書き込み系エンドポイントでは `Bun.password` によるパスワード検証とオーナー判定を実行します。コードは Hono 製 HTTP サーバーで、エントリポイントは `auth_manager/src/app/server.ts`、ルーティングは `auth_manager/src/app/routes/auth.ts` にまとまっています。

## サービスの役割と主なユースケース

- **実験参加のゲート管理**: `/api/v1/auth/experiments/:id/join` が実験コードとパスワードを突き合わせ、初回参加時に `participant` として自動登録します。パスワードフリーの実験はワンクリックで参加が完了します。
- **ロールの一元参照**: Session Manager や ERP サービスなど、上流でロール判定が必要なサービスは `/api/v1/auth/check` を呼び出すだけで権限を確認できます。呼び出し側はロール条件 (`owner` or `participant`) を指定するのみです。
- **参加者リストの監査**: 実験オーナーは参加者一覧エンドポイントを用いてロール・参加日時を確認し、その場でロール昇格/降格を実行できます。監査ログを兼ねており、実験ごとのアクセス管理を UI から完結させる狙いがあります。
- **ヘルス監視とフェイルセーフ**: DB 接続が失敗するとヘルスエンドポイントが 503 を返却するため、オーケストレーション層 (例: Kubernetes Liveness) からの再起動トリガとして利用できます。API ハンドラでも DB エラーを 500 として回収し、クライアントに明示的なエラーを返します。

## ランタイム構成

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `PORT` | `3000` | Bun の待受ポート。 |
| `DATABASE_URL` | 必須 | PostgreSQL 接続文字列。`dbPool` (`auth_manager/src/infrastructure/db.ts`) から利用。 |

## データベース利用

| テーブル | 操作 | 使用箇所 |
| --- | --- | --- |
| `experiments` | `SELECT password_hash` | 参加処理時のパスワード照合 (`join` ハンドラ)。 |
| `experiment_participants` | `INSERT`, `UPDATE`, `SELECT` | 参加登録、ロール変更、参加者一覧、`/check` 判定。 |

`experiment_participants` では `(experiment_id, user_id)` を主キーとし、`role` が `owner` / `participant` のいずれかであることを前提としています。ロール更新は `UPDATE ... RETURNING` により更新結果を返却します。

## ヘルスチェック

- `GET /health` : DB に `SELECT 1` を実行し、接続可否のみを返します。失敗時は 503。
- `GET /api/v1/health` : 上記に加え、`service` 名と `uptime`、`timestamp` を含む JSON を返します。

## API 詳細

### `POST /api/v1/auth/experiments/:experiment_id/join`

| 項目 | 内容 |
| --- | --- |
| 必須ヘッダー | なし |
| ボディスキーマ | `auth_manager/src/app/schemas/auth.ts` の `joinExperimentSchema` を参照。 |
| 主な検証 | `user_id` は必須文字列。実験にパスワードが設定されている場合、`password` が存在し `Bun.password.verify` に成功する必要があります。 |
| 処理 | `experiment_participants` に `role='participant'` で `INSERT ... ON CONFLICT DO NOTHING`。 |
| 成功レスポンス | `201 Created` + `{"message": "Successfully joined experiment"}`。 |

### `GET /api/v1/auth/experiments/:experiment_id/participants`

| 項目 | 内容 |
| --- | --- |
| 必須ヘッダー | `X-User-Id` (呼び出しユーザー)。 |
| 検証 | `isUserOwner` (`auth_manager/src/app/routes/auth.ts`) によりオーナー確認。失敗で 403。 |
| レスポンス | 実験の全参加者 (`user_id`, `role`, `joined_at`) を配列で返却。 |

### `PUT /api/v1/auth/experiments/:experiment_id/participants/:user_id`

| 項目 | 内容 |
| --- | --- |
| 必須ヘッダー | `X-User-Id` (呼び出しユーザー)。 |
| ボディ | `updateRoleSchema` (`auth_manager/src/app/schemas/auth.ts`) に準拠。`role` は `'owner'` か `'participant'`。 |
| 処理 | オーナー判定後、対象ユーザーのロールを更新。存在しない場合は 404。 |

### `POST /api/v1/auth/check`

| 項目 | 内容 |
| --- | --- |
| ボディ | `authCheckSchema` (`user_id`, `experiment_id`, `required_role`)。 |
| 判定ロジック | `required_role` が `owner` の場合は完全一致、`participant` の場合は `owner` も許可 (`authorizedRoles = ['owner','participant']`)。 |
| レスポンス | `{ "authorized": boolean }`。DB エラー時は 500。 |

## エラーハンドリング

- Hono の `app.onError` で 500 を JSON `{ "error": "Internal Server Error" }` として統一。
- DB 接続エラーはログ出力後 500。
- 認証系の不備（ヘッダー欠如、パスワード不一致）は 4xx を返却します。

## 参考ファイル

- ルーティング: `auth_manager/src/app/routes/auth.ts`
- スキーマ定義: `auth_manager/src/app/schemas/auth.ts`
- DB 接続: `auth_manager/src/infrastructure/db.ts`
