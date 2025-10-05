---
service_name: "Session Manager Service"
description: "実験のライフサイクル（定義、セッション管理）と、関連サービスへの処理の委譲を担う司令塔。"

inputs:
  - source: "Frontend Client (e.g., Smartphone App)"
    data_format: "HTTP POST/GET (JSON, Multipart/form-data)"
    schema: "`/api/v1/experiments`および`/api/v1/sessions`配下のエンドポイント群"
  - source: "Auth Manager Service (via middleware)"
    data_format: "Internal HTTP Call"
    schema: "各エンドポイントの権限（owner/participant）を検証するために内部的に呼び出される。"

outputs:
  - target: "PostgreSQL"
    data_format: "SQL INSERT/UPDATE"
    schema: "`experiments`, `sessions`, `experiment_participants`, `session_events`テーブルへの書き込み"
  - target: "Stimulus Asset Processor Service (via RabbitMQ)"
    data_format: "AMQP Message (Job Payload)"
    schema: "刺激アセット（CSVとファイル群）の永続化処理を依頼するジョブ。Queue: `stimulus_asset_queue`"
  - target: "DataLinker Service (via RabbitMQ)"
    data_format: "AMQP Message (Job Payload)"
    schema: "セッション終了後のデータ紐付け処理を依頼するジョブ。Queue: `data_linker_queue`"
  - target: "BIDS Exporter Service (as a proxy)"
    data_format: "Internal HTTP Call"
    schema: "BIDSエクスポートリクエストをそのまま転送する。"
---

## 概要

`Session Manager`は、実験の「設計」から「実施」、「記録」までのライフサイクル全体を管理する司令塔となるサービスです。実験の作成、セッションの開始・終了の記録といった中心的な役割を担います。また、自身で重い処理は行わず、刺激アセットの登録やデータ紐付けといったタスクを、RabbitMQを介してそれぞれの専門サービスに**委譲（delegate）**するのが大きな特徴です。各操作は、リクエストヘッダーの`X-User-Id`に基づき、`Auth Manager`サービスと連携する`requireAuth`ミドルウェアによって保護されます。

## 詳細

-   **責務**:
    -   「実験の定義と参加者の管理」
    -   「セッションのライフサイクル（開始・終了）の管理と、イベント実績の記録」
    -   「専門的な処理（刺激アセット永続化、データ紐付け）のジョブを適切な非同期ワーカーへ投入すること」

---

## スキーマ変更に伴う影響

新しいデータスキーマでは、`Collector`が受信する各データペイロードに`session_id`が含まれるようになります。これはセッション管理のアーキテクチャに重要な変更をもたらします。

### 1. `session_id`の役割の変化

- **旧:** `session_id`は主に`Session Manager`のデータベース内でセッションを識別するための内部的なIDでした。
- **新:** `session_id`は、データストリーム自体に含まれる**分散コンテキストID**としての役割を担います。各データが「どのセッションに属するか」を自己記述するようになるため、後続のサービスは`Session Manager`に問い合わせることなく、データのコンテキストを理解できます。

### 2. セッション開始フローの更新

`POST /api/v1/sessions/start`エンドポイントの役割がより重要になります。

1.  クライアント（スマホアプリ）がこのエンドポイントを呼び出します。
2.  `Session Manager`は`sessions`テーブルに新しいレコードを作成し、一意の`session_id`を生成します。
3.  **`Session Manager`は、生成した`session_id`をレスポンスボディに含めてクライアントに返却する必要があります。**
4.  クライアントは、受け取った`session_id`を、以降`Collector`に送信する全てのセンサーデータパケットの`session_id`フィールドに設定します。

### 3. 他サービスとの依存関係の低下

この変更により、各サービスはより疎結合になります。

- `Processor`サービスは、受信したAMQPメッセージのヘッダーから`session_id`を直接取得し、`raw_data_objects`テーブルに保存できます。
- `Data Linker`や`BIDS Exporter`といった後続サービスも、処理対象のデータに紐づく`session_id`をデータベースやメッセージヘッダーから直接取得できるため、`Session Manager`への実行時クエリが不要になります。

`Session Manager`は、セッションの**マスターデータ（いつ、誰が、どの実験のセッションを開始・終了したか）**を管理する唯一の権威であることに変わりはありませんが、そのIDの使い方がより分散的・効率的になります。

---

## APIエンドポイント

### 実験管理 (`/api/v1/experiments`)

-   `POST /`
    -   **機能**: 新規実験を作成します。
    -   **権限**: 全ての認証済みユーザー。
    -   **詳細**: リクエスト元のユーザー（`X-User-Id`ヘッダー）を`owner`として`experiment_participants`テーブルに自動的に登録します。オプションでパスワードを設定可能です。

-   `GET /`
    -   **機能**: 自分が参加している実験の一覧を取得します。
    -   **権限**: 全ての認証済みユーザー。

-   `POST /:experiment_id/stimuli`
    -   **機能**: 実験で使用する刺激アセット（定義CSVとファイル群）の登録を**依頼**します。
    -   **権限**: `owner`のみ。
    -   **処理フロー**: このエンドポイントはファイルの永続化を直接行いません。代わりに、アップロードされたCSVとファイル群を検証し、それらをペイロードとして`stimulus_asset_queue`にジョブを投入します。実際の処理は`Stimulus Asset Processor`サービスが非同期に実行します。

-   `GET /:experiment_id/stimuli`
    -   **機能**: 指定された実験に登録済みの刺激アセットの一覧を取得します。
    -   **権限**: `participant`以上（`owner`も含む）。

-   `POST /:experiment_id/export`
    -   **機能**: `BIDS Exporter`サービスの非同期エクスポート開始APIへのプロキシとして機能します。
    -   **権限**: `owner`のみ。

### セッション管理 (`/api/v1/sessions`)

-   `POST /start`
    -   **機能**: セッションの開始を記録します（事前登録）。
    -   **権限**: `participant`以上。
    -   **詳細**: `sessions`テーブルに基本的な情報（`session_id`, `user_id`, `start_time`など）を持つレコードを作成します。これにより、システムは実行中のセッションを把握できます。

-   `POST /end`
    -   **機能**: セッションの終了と、その実績（イベントログ）を記録します。
    -   **権限**: `participant`以上。
    -   **処理フロー**:
        1.  `multipart/form-data`でJSONメタデータとイベントログCSVを受け取ります。
        2.  `sessions`テーブルの既存レコードを更新します（`end_time`, `clock_offset_info`など）。
        3.  `events_log_csv`が存在する場合、対象セッションの既存イベントを**全て削除（DELETE）**し、CSVの内容を`session_events`テーブルに**再登録（INSERT）**します。これにより、ログの修正・再アップロードが安全に行えます。
        4.  DB更新が完了後、`DataLinker`サービスのために`data_linker_queue`へデータ紐付けジョブを投入します。

### 刺激アセットダウンロード (`/api/v1/stimuli`)

-   `GET /calibration/download/:filename`
    -   **機能**: グローバルなキャリブレーション用刺激ファイルをダウンロードします。
    -   **権限**: 全ての認証済みユーザー。

-   `GET /:experiment_id/download/:filename`
    -   **機能**: 特定の実験に紐づく刺激ファイルをダウンロードします。
    -   **権限**: `participant`以上。
    -   **詳細**: 両エンドポイントとも、MinIOからファイルを直接クライアントにストリーミングします。