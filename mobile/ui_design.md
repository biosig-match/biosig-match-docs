# UI/UX Design Document

## 1. コンセプト

- **テーマ**: ダークテーマをベースにシアン/ブルーのアクセントカラー。眼精疲労を抑えつつ、医療機器らしい信頼感を演出します。
- **タイポグラフィ**: 標準の `ThemeData.dark()` をベースに、タイトルは太字、補助説明はグレー (`Colors.white70`) を使用。
- **アクセシビリティ**: 状態メッセージは `SnackBar` とカード上のテキストで提示し、操作失敗時でも状況を把握できるようにしています。
- **ナビゲーション**: アプリバー左にハンバーガーメニュー (`AppDrawer`) を配置。主要画面（ホーム / 実験 / 刺激提示 / 解析 / BIDS など）へ遷移します。

---

## 2. 画面構成

アプリは以下の主要画面で構成されます。

- **ホーム画面 (`HomeScreen`)**: BLE 接続状態・実験選択・リアルタイム波形を集約。セッション開始/終了のハブ。
- **実験一覧 (`ExperimentsScreen`)**: 実験の選択・作成・BIDS エクスポート操作。
- **刺激提示 (`StimulusPresentationScreen`)**: キャリブレーション/本番刺激を全画面表示。イベントログを自動生成。
- **セッション完了 (`SessionSummaryScreen`)**: CSV の確認と `POST /sessions/end` 送信。
- **リアルタイム解析 (`AnalysisScreen`)**: PSD / コヒーレンス画像をタブ表示。
- **BIDS エクスポート / ERP 解析画面**: Drawer から遷移し、各 Provider の状態を表示。

---

## 3. 画面詳細

### 3.1 ホーム画面

- **アプリバー**: タイトル「EEG BIDS Collector」、右側にデバイス選択 `PopupMenuButton` と接続状態アイコン (接続時: `Icons.bluetooth_connected`)。
- **上部カード**:
  - 選択中の実験名/説明 (`ListTile`)。
  - セッション状態と操作ボタン：
    - `FilledButton`「セッション開始」でダイアログを開き、`アプリ内刺激提示` / `外部アプリ` を選択。
    - `FilledButton`「接続解除」により `BleProvider.disconnect()` を呼び出し。
- **データ表示**:
  - `EegChart`: `_displayDataBuffer` の 5 秒分をチャート表示。
  - `ValenceChart`: `valenceHistory` を折れ線で描画。
- **フローティング要素**:
  - 接続状態に応じて `SnackBar` を表示（例: スキャン開始/失敗）。
- **権限リクエスト**: `initState` で BLE・位置情報・カメラ・マイク権限を要求するダイアログが自動表示される。

### 3.2 実験一覧画面

- **アプリバー**: 「実験一覧」、右に「＋」(新規作成) と更新 (`Icons.refresh`)。
- **リスト**: `Card` + `ListTile` のリスト表示。
  - タップで実験を選択しホームへ戻る。
  - 右側のアイコンボタン (`Icons.archive_outlined`) で BIDS エクスポートダイアログ。
- **新規作成ダイアログ**:
  - 名前・説明・提示順 (`DropdownButtonFormField`) を入力。
  - `FilledButton`「作成」で `SessionProvider.createExperiment` を呼び出す。

### 3.3 刺激提示画面

- **状態遷移**: `ScreenState` (loading → ready → running → finished) を UI に反映。
- **ロード中**: プログレスインジケータとテキスト「刺激情報を準備中...」。
- **準備完了**: `ElevatedButton`「刺激提示を開始」。
- **実行中**:
  - 背景は黒、中央に刺激画像または待受アイコン (`Icons.add`)。
  - 1 秒提示 → 1.5 秒クロス表示を `Timer` で制御。
  - 画面下から戻る操作 (`onWillPop`) を禁止し、誤操作を防止。
- **完了時**: `SessionSummaryScreen` へ自動遷移。CSV 文字列を渡す。

### 3.4 セッション完了画面

- **概要カード**: 開始・終了時刻、実験名を表示。
- **イベントログ**:
  - 生成済み CSV の件数表示 or ファイル選択ボタン。
  - アプリ内生成の場合はボタンを無効化。
- **完了ボタン**: `FilledButton.icon`「完了してアップロード」。押下で `endSessionAndUpload` を実行し、ホーム画面まで戻る。

### 3.5 リアルタイム解析画面

- **AppBar + TabBar**: 「パワースペクトル」「コヒーレンス」の 2 タブ。
- **ステータスメッセージ**: ポーリング結果をテキストで表示。
- **画像ビューア**: Base64 画像を `Image.memory` で表示。データなしの場合はプレースホルダ文言を表示。
- **ポーリング制御**: `initState` でポーリング開始、`dispose` で停止。

### 3.6 BIDS / ERP 画面 (Drawer 内)

- **BIDS Export Screen**:
  - タスク一覧 (`ListView`) とステータス表示。
  - 各タスクの状態に応じてダウンロードボタンを活性化。
- **Neuro Marketing Screen**:
  - 最新解析結果 (`ErpAnalysisResult`) のサマリーをカード表示。
  - 「解析をリクエスト」ボタンで `requestAnalysis` を呼び出し。

---

## 4. ステートマシンとフィードバック

- **BLE 接続状態**: `statusMessage` を画面上部で常時表示。スキャン中・接続中・切断などを明確にする。
- **セッション状態**: `SessionProvider.statusMessage` をホーム画面のカード内に表示。
- **エラーハンドリング**:
  - API 失敗時: `SnackBar` + Provider の `_statusMessage` 更新。
  - 画像ダウンロード失敗時: Stimulus Provider が `_errorMessage` をセットし、UI でトーストを表示。

---

## 5. 権限と設定フロー

1. アプリ初回起動で権限ダイアログが連続表示。
2. 許可後にホーム画面の BLE デバイス選択メニューが利用可能に。
3. BLE 接続中でも Drawer から他画面へ遷移可能。再接続時はホームに戻るよう SnackBar で誘導。

---

## 6. デザイン指針まとめ

- ホーム画面で主要 KPI (接続状態・波形・バレンス) を即時把握できるよう、カードを縦並びで配置。
- 刺激提示中は没入感と安全性を重視し、背景黒 + 全画面表示 + ボタン非表示。
- セッション完了画面は「やり残しがないか」を確認しやすいよう、概要→CSV→完了の縦フロー。
- 解析系画面では重い処理待ちが発生するため、ステータスメッセージを頻繁に更新し、ユーザーに進捗を提示。
