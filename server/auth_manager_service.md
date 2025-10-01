---

### Auth Manager Service

`service_name: "Auth Manager Service"`
`description: "実験へのアクセス権（誰が、どの実験に、何をできるか）を一元管理する、セキュリティの要となるサービス。"`

`inputs:`
  `- source: "各種サービス (Session Manager, BIDS Exporterなど)"`
    `data_format: "HTTP GET (Internal API Call)"`
    `schema: "ユーザーIDと実験IDを含む権限確認リクエスト"`
  `- source: "Smartphone App"`
    `data_format: "HTTP POST/GET/PUT (JSON)"`
    `schema: "実験への参加リクエスト、参加者一覧の取得、ロール変更リクエスト"`

`outputs:`
  `- target: "PostgreSQL"`
    `data_format: "SQL INSERT/UPDATE/SELECT"`
    `schema: "experiment_participantsテーブルの操作"`
  `- target: "リクエスト元サービス"`
    `data_format: "HTTP Response (JSON)"`
    `schema: "{ authorized: true/false }"`

---

#### 概要

`Auth Manager`は、本システムにおける全ての**認証・認可**を司る専用サービスです。「実験」という閉じられた空間（部屋）へのアクセス制御に特化し、誰が実験のオーナーで、誰が参加者なのか、といった情報を一元管理します。他のサービスは、何らかの操作を行う前に必ず本サービスに権限の有無を問い合わせる必要があります。

#### 詳細

* **責務**: **「ユーザーと実験の関連付け、およびロール（役割）に基づいたアクセス権の判定」**。
* **コアコンセプト（部屋制）**:
    * 実験は、作成者（最初のオーナー）だけが入れる閉じた「部屋」として作成されます。
    * オーナーは、実験ID（と、必要であればパスワード）を共有することで、特定のユーザーを実験に招待できます。
    * 参加者は、招待情報を使って「部屋」への参加リクエストを送信します。
* **API エンドポイント (例)**:
    * `POST /api/v1/auth/experiments/{experiment_id}/join`: 参加者が実験に参加するためのエンドポイント。
    * `GET /api/v1/auth/experiments/{experiment_id}/participants`: オーナーが参加者一覧とロールを確認するためのエンドポイント。
    * `PUT /api/v1/auth/experiments/{experiment_id}/participants/{user_id}`: オーナーが参加者のロールを変更する（例：共同研究者をオーナーに昇格させる）ためのエンドポイント。
    * `GET /api/v1/auth/check`: **(内部API)** 他サービスからの権限確認用エンドポイント。リクエストボディに `{ user_id, experiment_id, required_role }` などを含み、操作が許可されるかどうかの真偽値を返す。
