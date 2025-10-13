# biosig-match-docs

本リポジトリは EEG プラットフォームの設計・仕様ドキュメントを「Docs as Code」方式で管理します。コードと同様に Pull Request / レビューの対象となるため、再現性のある情報と根拠を記載してください。

## 📄 ドキュメント作成ルール

1. **YAML Front Matter を必須化** し、ドキュメント間で機械的に情報を取得できるようにします。先頭に以下のキーを記述してください。

   ```yaml
   ---
   service_name: "Human readable 名称"
   component_type: "service | queue | storage | database | client | hardware | other"
   description: "1 行の要約"
   inputs:
     - source: "データの入力元"
       data_format: "通信方式やファイル形式"
       schema: |
         実際のデータ構造を具体的に記述（Zod/Pydantic の定義パス、JSON 例、CSV 列など）
   outputs:
     - target: "出力先"
       data_format: "出力形式"
       schema: |
         実装が扱う実データを明示
   ---
   ```

   - `component_type` はデータフロー図のノード分類に使用します。該当しない場合は `other`。
   - `schema` には**曖昧な説明ではなく実装で使用している構造**（フィールド一覧、型、テーブル名など）を必ず記載してください。
   - 参照するコードがある場合はファイルパス (例: `session_manager/src/app/routes/sessions.ts`) を併記するとレビューが容易です。

2. ドキュメント本文では、
   - 実装レベルの仕様（エンドポイントの入出力、キューのメッセージ形式、DB テーブルのカラム定義など）を記述する。
   - 変更が発生した際に追随すべきコードのパスやテスト手順を残す。

3. 既存ドキュメントを更新する場合は **「何が最新実装で、どこがコードと紐づいているか」** がひと目で分かるようにすること。

## 🗺 データフロー図の更新

`scripts/generate_flow.py` は Front Matter を解析して `architecture/02_data-flow.md` を自動更新します。

```bash
cd biosig-match-docs
python scripts/generate_flow.py
```

- スクリプトは Front Matter からノード・エッジを抽出します。`schema` が空のエントリは線に反映されないため注意してください。
- 図は `architecture/data-flow-diagram.svg` として出力され、`02_data-flow.md` に埋め込まれます。

## 📁 ディレクトリ構成

- `architecture/` : アーキテクチャ全体図や設計思想。
- `server/` : サーバーサイド各コンポーネントの仕様書。
- `hardware/`, `firmware/`, `mobile/` : ハード・ファーム・モバイル領域のドキュメント。
- `scripts/` : ドキュメント自動化スクリプト。
- `_templates/` : 新規ドキュメント作成時のテンプレート。

## ✅ レビュー時のポイント

- Front Matter の `schema` が実装と一致しているか。
- エンドポイント／メッセージの入出力が、該当コード (Zod/Pydantic/SQL) と矛盾しないか。
- 依存関係や副作用 (DB 更新やキュー投入など) が明記されているか。

この README 自体も仕様変更時に必ず更新してください。
