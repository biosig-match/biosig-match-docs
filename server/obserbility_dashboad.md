# Observability Dashboard サービス概要

## 目的

- マイクロサービス間のデータフロー、RabbitMQ キューの滞留状況、DB/MinIO の利用状況をリアルタイムに可視化する。
- BIDS エクスポートタスクの進捗や DB テーブル/MinIO バケット内のデータを監査担当者が直接確認できるようにする。

## 実装概要

| 項目 | 内容 |
| --- | --- |
| サービス名 | `observability_dashboard` |
| 実行環境 | Bun + Hono |
| 依存先 | RabbitMQ Management API, PostgreSQL, MinIO |
| 公開ポート | `OBSERVABILITY_PORT` (デフォルト 8090) |

### 主なエンドポイント

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/` | グラフ表示付き SPA。D3.js でリアルタイム可視化。 |
| `GET` | `/health` | RabbitMQ / PostgreSQL / MinIO のヘルスチェック集約。 |
| `GET` | `/api/v1/graph` | サービス/キュー/ストレージ間のノード・エッジ情報と各メトリクス。 |
| `GET` | `/api/v1/tasks` | `export_tasks` テーブルからエクスポートタスク一覧を取得 (既定 100 件)。 |
| `GET` | `/api/v1/db/tables` | 利用者スキーマに存在するテーブルのサイズ・行数推定を返却。 |
| `GET` | `/api/v1/db/tables/{schema}/{table}` | 任意テーブルのサンプル行を最大 500 行まで取得。 |
| `GET` | `/api/v1/db/tables/{schema}/{table}/columns` | テーブル列情報を返却。 |
| `GET` | `/api/v1/storage/buckets` | MinIO バケットとサンプルオブジェクトの一覧。 |

### 表示内容

1. **データフロー・グラフ**  
   - Nginx → Collector → RabbitMQ → Processor → PostgreSQL/MinIO など主要サービス間エッジを D3 Force Layout で描画。  
   - ノード色で状態表示 (OK/Degraded/Error/Unknown)。キュー滞留、コンシューマ数、処理レートなどをツールチップで確認可能。

2. **BIDS エクスポートタスク**  
   - `export_tasks` テーブルから進捗 (0–100%)、ステータス、最終更新時刻を表示。

3. **DB テーブル指標**  
   - `pg_stat_user_tables` を用いた推定行数・テーブルサイズ (Total/Table/Index/Toast)。  
   - 主要テーブルを上位 10 件表示し、詳細は API から取得可能。

4. **MinIO バケットプレビュー**  
   - 各バケットの作成日時と先頭数件のオブジェクト名＋サイズを取得。監査時の確認に利用。

## 環境変数

`.env` またはデプロイ設定に以下を追加/確認する。

```env
# 公開ポート (任意)
OBSERVABILITY_PORT=8090

# ダッシュボードの自動更新間隔 (ms, 任意)
OBSERVABILITY_DASHBOARD_REFRESH_MS=4000

# 既存値を流用 (設定済みの場合は不要)
RAW_DATA_EXCHANGE=raw_data_exchange
PROCESSING_QUEUE=processing_queue
MEDIA_PROCESSING_QUEUE=media_processing_queue
DATA_LINKER_QUEUE=data_linker_queue
EVENT_CORRECTION_QUEUE=event_correction_queue
STIMULUS_ASSET_QUEUE=stimulus_asset_queue
```

> **Note:** RabbitMQ Management プラグインは既に有効化済み。`RABBITMQ_MGMT_PORT` が 15672 にマッピングされていれば追加設定は不要。

## 監査ワークフロー例

1. ブラウザで `http://localhost:8090/` (もしくは `OBSERVABILITY_PORT`) を開く。
2. データフロー図でキュー滞留の有無を確認し、異常ノードのツールチップから詳細を取得。
3. 「BIDS エクスポートタスク」パネルで対象タスクの進捗を確認し、必要なら `/api/v1/tasks?limit=200` で詳細を取得。
4. 「DB テーブル」で該当テーブルを選び、`/api/v1/db/tables/public/export_tasks` などからサンプルデータを取得。
5. 「MinIO バケット」パネルで対象バケットのサンプルオブジェクトを確認し、必要に応じて MinIO Console で完全データにアクセス。

## セキュリティ考慮

- 重要 API は読み取り専用。書込みは行わない設計とし、監査用に限定。
- 将来的に Basic 認証または内部 VPN のみアクセス可能なネットワークセグメントで公開することを推奨。
- RabbitMQ 管理 API の認証情報は既存の `RABBITMQ_USER`/`RABBITMQ_PASSWORD` に依存し、追加の資格情報は作成していない。

## 今後の拡張候補

- Prometheus/Grafana 互換メトリクスのエクスポート。
- WebSocket/SSE によるサブ秒更新。
- RBAC を用いた閲覧権限の細分化。
