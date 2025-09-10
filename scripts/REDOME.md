MyProject ドキュメントリポジトリ
このリポジトリは、MyProject に関連するすべての設計・仕様ドキュメントを一元管理します。

データフロー図について
このリポジトリのデータフロー図 (architecture/data-flow-diagram.svg) は、各コンポーネントのマークダウンファイルから自動生成されます。

図の更新は、ローカル環境で手動実行します。これは、過去に GitHub の Mermaid レンダラーで解決困難なパースエラーが頻発したため、より安定した Graphviz ツールに移行した経緯によります。

✍️ データフロー図の更新方法

1. 初回のみ：環境構築
   図を生成するには、お使いの PC にいくつかのツールをインストールする必要があります。これは一度だけで済む作業です。

a. Graphviz のインストール
お使いの OS に合わせて、ターミナルで以下のコマンドを実行してください。

Windows (Chocolatey を使用):

# もし choco コマンドがなければ、まず PowerShell を管理者として実行し、

# Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('[https://community.chocolatey.org/install.ps1](https://community.chocolatey.org/install.ps1)'))

# を実行して Chocolatey をインストールしてください。

choco install graphviz

macOS (Homebrew を使用):

brew install graphviz

Linux (Debian/Ubuntu):

sudo apt-get update && sudo apt-get install -y graphviz

b. Python ライブラリのインストール
プロジェクトのルートディレクトリで、以下のコマンドを実行します。

python -m pip install -r scripts/requirements.txt

2. 図の生成・更新
   ドキュメント（.md ファイル）を編集した後、図を更新するには、プロジェクトのルートディレクトリで以下のコマンドを 1 つ実行するだけです。

python scripts/generate_flow.py

これにより、architecture/data-flow-diagram.svg と architecture/02-data-flow.md の 2 つのファイルが自動で更新されます。

3. 変更のコミット
   最後に、変更したドキュメントと、上記コマンドで更新された 2 つのファイル (.svg と .md) の両方を Git にコミットしてください。

git add .
git commit -m "docs: データフロー図と関連ドキュメントを更新"
git push
