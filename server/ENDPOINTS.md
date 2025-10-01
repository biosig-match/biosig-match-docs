# Backend API Endpoints

プロジェクト内で提供されている各マイクロサービスのエンドポイントとリクエスト例をまとめています。スマホアプリのバックエンド設計時に参照してください。

## Session Manager

- `GET /` : 稼働確認用。プレーンテキストで `Session Manager Service is running.` を返却します。([session_manager/src/index.ts](session_manager/src/index.ts))
- `GET /api/v1/experiments` : `X-User-Id` ヘッダー必須。ユーザーが参加している実験の一覧を JSON 配列で返します。
- `POST /api/v1/experiments` : JSON `{"name","description?","password?","presentation_order?"}` を受け取り、新規実験を作成します。作成者は自動的に owner として登録されます。
- `POST /api/v1/experiments/{experiment_id}/stimuli` : owner 権限。`stimuli_definition_csv` と複数の `stimulus_files` を含む multipart/form-data を受け取り、CSV とファイル名の整合性を検証後、Stimulus Asset Processor 向けジョブを RabbitMQ に投入します。
- `GET /api/v1/experiments/{experiment_id}/stimuli` : participant 以上の権限。登録済み刺激アセットのリストを JSON で返却します。
- `POST /api/v1/experiments/{experiment_id}/export` : owner 権限。BIDS Exporter へフォワードし、上流サービスのレスポンス (`{task_id,status,message,...}` など) を透過的に返します。
- `POST /api/v1/sessions/start` : participant 権限。JSON `{"session_id","user_id","experiment_id","start_time","session_type"}` を保存し、重複送信は無視します。
- `POST /api/v1/sessions/end` : participant 権限。multipart/form-data で `metadata`(JSON文字列) と `events_log_csv`(任意) を送り、CSV のバリデーション後に session_events を再作成します。完了後 DataLinker 向けジョブをキューイングします。
- `GET /api/v1/calibrations` : `X-User-Id` を確認し、グローバルキャリブレーションアセット一覧を返却します。
- `GET /api/v1/stimuli/download/{filename}` : `X-User-Id` 必須。MinIO から該当アセットをストリーム返却します。

```bash
curl -H 'X-User-Id: user-123' http://session_manager:3000/api/v1/experiments
curl -X POST http://session_manager:3000/api/v1/experiments \
  -H 'Content-Type: application/json' -H 'X-User-Id: owner-1' \
  -d '{"name":"Brand Test","description":"A/B","password":"abcd","presentation_order":"random"}'

curl -X POST http://session_manager:3000/api/v1/experiments/${EXPERIMENT_ID}/stimuli \
  -H 'X-User-Id: owner-1' \
  -F 'stimuli_definition_csv=@stimuli_definition.csv' \
  -F 'stimulus_files=@face01.png' -F 'stimulus_files=@house01.png'

curl -X POST http://session_manager:3000/api/v1/sessions/end \
  -H 'X-User-Id: participant-9' \
  -F 'metadata={"session_id":"sess-1","user_id":"participant-9","experiment_id":"...","device_id":"dev-7","start_time":"2025-09-30T10:00:00Z","end_time":"2025-09-30T10:30:00Z","session_type":"main_integrated"}' \
  -F 'events_log_csv=@main_task_events.csv'
```

## Auth Manager

- `GET /` : サービス稼働確認用テキストを返します。
- `POST /api/v1/auth/experiments/{experiment_id}/join` : JSON `{"user_id","password?"}` を受け取り、実験への参加を登録します。パスワード設定済みの場合は検証を行います。
- `GET /api/v1/auth/experiments/{experiment_id}/participants` : `X-User-Id` が owner の場合に参加者一覧を返します。
- `PUT /api/v1/auth/experiments/{experiment_id}/participants/{user_id}` : owner のみ。JSON `{"role":"owner|participant"}` でロール変更を行います。
- `POST /api/v1/auth/check` : JSON `{"user_id","experiment_id","required_role"}` を受け取り、`{"authorized":true/false}` を返却。Session Manager や ERP Neuro-Marketing で利用されています。

```bash
curl -H 'X-User-Id: owner-1' http://auth_manager:3000/api/v1/auth/experiments/${EXPERIMENT_ID}/participants
curl -X PUT http://auth_manager:3000/api/v1/auth/experiments/${EXPERIMENT_ID}/participants/user-9 \
  -H 'Content-Type: application/json' -H 'X-User-Id: owner-1' \
  -d '{"role":"participant"}'
```

## Collector

- `GET /api/v1/health` : サービス状態と RabbitMQ 接続状況を返します。
- `POST /api/v1/data` : JSON `{"user_id","payload_base64"}` を受け取り、`raw_data_exchange` へ publish します。
- `POST /api/v1/media` : multipart/form-data で `file`、`user_id`、`session_id`、`mimetype`、`original_filename`、必要に応じて `timestamp_utc` または `start_time_utc/end_time_utc` を受け取り、`media_processing_queue` に送信します。

```bash
curl -X POST http://collector:3000/api/v1/media \
  -F 'file=@photo.png' \
  -F 'user_id=user-3' -F 'session_id=sess-1' \
  -F 'mimetype=image/png' -F 'original_filename=photo.png' \
  -F 'timestamp_utc=2025-09-30T10:05:00Z'
```

## BIDS Exporter

- `GET /health` : `{status:"ok"}` を返すヘルスチェック。
- `POST /api/v1/experiments/{experiment_id}/export` : UUID を受け取り、`{task_id,status,message,status_url}` を `202 Accepted` で返します。バックグラウンドで BIDS 生成を開始します。
- `GET /api/v1/export-tasks/{task_id}` : タスクの進捗と結果パスを返します。
- `GET /api/v1/export-tasks/{task_id}/download` : 完了済みのタスクについて ZIP をストリーム返却します。
- `POST /internal/v1/create-bids-for-analysis` : JSON `{"experiment_id"}` を受け取り、同期的に BIDS データを生成し `{experiment_id,bids_path,message}` を返します (ERP Neuro-Marketing 専用)。

```bash
curl http://bids_exporter:8000/api/v1/export-tasks/${TASK_ID}
curl -OJ http://bids_exporter:8000/api/v1/export-tasks/${TASK_ID}/download
```

## BIDS Manager

- `POST /api/v1/experiments` : `{participant_id,device_id,metadata}` を受け取り、新規実験 ID を払い出します。
- `POST /api/v1/experiments/{experiment_id}/events` : CSV ファイル `file` を解析し、トリガと照合してイベントを登録、実験を完了状態に更新します。
- `POST /api/v1/experiments/{experiment_id}/export` : バックグラウンドで BIDS エクスポートを実行し、`{status:"accepted",task_id}` を返します。
- `GET /api/v1/export-tasks/{task_id}` : エクスポートタスクのステータスを返します。
- `GET /api/v1/downloads/{filepath}` : 生成された BIDS ファイルをダウンロードします。

```bash
curl -X POST http://bids_manager:5001/api/v1/experiments/${EXPERIMENT_ID}/export
curl -OJ http://bids_manager:5001/api/v1/downloads/sub-001_ses-20250930_task-erp_edf.zip
```

## ERP Neuro-Marketing

- `GET /health` : `{status:"ok"}` を返す稼働確認エンドポイント。
- `POST /api/v1/neuro-marketing/experiments/{experiment_id}/analyze` : `X-User-Id` が owner であることを検証後、BIDS Exporter の内部 API と連携し、`{"experiment_id","summary","recommendations":[]}` を返します。

```bash
curl -X POST http://erp_neuro_marketing:8001/api/v1/neuro-marketing/experiments/${EXPERIMENT_ID}/analyze \
  -H 'X-User-Id: owner-1'
```

## Realtime Analyzer

- `GET /api/v1/users/{user_id}/analysis` : 最新の解析結果 (PSD 画像とコヒーレンス画像の Base64、タイムスタンプ) を返します。データ不足時は `202 Accepted` と状況メッセージを返却します。

```bash
curl http://realtime_analyzer:5002/api/v1/users/user-3/analysis
```

---
これらの API は RabbitMQ、PostgreSQL、MinIO と連携し、長時間処理はタスク監視エンドポイント (`status_url`) をポーリングする非同期設計になっています。スマホアプリからのアクセスでは、`X-User-Id` ヘッダーによる認証・権限チェックと、owner / participant ロールに基づくフロー設計を考慮してください。
