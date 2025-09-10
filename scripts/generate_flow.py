import re
import yaml
from pathlib import Path
import unicodedata
import os

def to_mermaid_id(text, components_meta):
    """
    文字列をMermaid.jsの有効なノードIDに変換します。
    - 日本語の表示名などから、定義済みのコンポーネントIDへのマッピングを試みます。
    - マッピングが見つからない場合は、一般的なサニタイズ処理を適用します。
    """
    if not isinstance(text, str):
        return "" # textがNoneなどの場合にエラーを防ぐ

    normalized_text = unicodedata.normalize('NFKC', text).strip()

    # --- 変更点 1: 表示名から定義済みIDへの逆引きを試みる ---
    # これにより、YAMLに書かれた日本語名がCOMPONENTS_METAの英語IDに正しく変換される
    for component_id, meta in components_meta.items():
        # metaのlabelからHTMLタグ(<br>)を除外して比較
        label_without_br = meta.get("label", "").replace("<br>", " ")
        if normalized_text == label_without_br or normalized_text == component_id:
            return component_id

    # --- 変更点 2: 正規表現ベースの変換を改善 ---
    # 汎用的なクリーンアップ処理に絞り、予測可能性を高める
    
    # かっこ（）とその中身を削除
    text = re.sub(r'[\(（].*?[\)）]', '', normalized_text)
    
    # 一般的な区切り文字をアンダースコアに置換
    text = re.sub(r'[\s/,-]+', '_', text)
    
    # 有効なID文字（英数字とアンダースコア）以外を削除
    text = re.sub(r'[^\w_]', '', text)
    
    return text.strip('_')

def parse_markdown_frontmatter(file_path):
    """
    マークダウンファイルからYAMLフロントマターを解析します。
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except IOError:
        return None
    
    match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match: return None
        
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        print(f"Error parsing YAML in {file_path}: {e}")
        return None

def main():
    root_dir = Path(__file__).parent.parent
    output_file = root_dir / "architecture" / "02_data-flow.md"
    
    # --- 1. Define the graphical structure (subgraphs, icons, etc.) ---
    # IDはMermaidで有効な一意の識別子とする
    COMPONENTS_META = {
        'User': {"label": "User", "icon": "fa:fa-user"},
        'Firmware_BLE': {"label": "Firmware (BLE)", "icon": "fa:fa-microchip"},
        'SmartphoneApp': {"label": "Smartphone App", "icon": "fa:fa-mobile-alt"},
        'CollectorService': {"label": "Collector Service", "icon": "fa:fa-server"},
        'RawDataExchange': {"label": "RabbitMQ Exchange<br>(raw_data_exchange)", "icon": "fa:fa-exchange"},
        'ProcessingQueue': {"label": "Processing Queue", "icon": "fa:fa-inbox"},
        'AnalysisQueue': {"label": "Analysis Queue", "icon": "fa:fa-inbox"},
        'ProcessorService': {"label": "Processor Service", "icon": "fa:fa-cogs"},
        'RealtimeAnalyzerService': {"label": "Realtime Analyzer", "icon": "fa:fa-chart-line"},
        'MinIO': {"label": "MinIO<br>(Object Storage)", "icon": "fa:fa-database"},
        'PostgreSQL': {"label": "PostgreSQL<br>(Metadata DB)", "icon": "fa:fa-database"},
        'SessionManagerService': {"label": "Session Manager", "icon": "fa:fa-tasks"},
        'BIDSExporterService': {"label": "BIDS Exporter", "icon": "fa:fa-file-archive"},
        'DataLinkageWorker': {"label": "Async Task Queue<br>(DataLinker)", "icon": "fa:fa-rocket"}
    }
    
    SUBGRAPH_STRUCTURE = {
        "External Actors": ['User', 'Firmware_BLE'],
        "Mobile Client": ['SmartphoneApp'],
        "API & Data Ingestion": ['CollectorService', 'RawDataExchange', 'ProcessingQueue', 'AnalysisQueue'],
        "Backend Processing": ['ProcessorService', 'RealtimeAnalyzerService'],
        "Storage Layer": ['MinIO', 'PostgreSQL'],
        "Management & Export": ['SessionManagerService', 'BIDSExporterService', 'DataLinkageWorker']
    }

    # --- 2. Discover connections from .md files ---
    connections = set()
    discovered_ids = set()

    # --- 変更点 3: to_mermaid_idに関数を渡せるようにする ---
    id_converter = lambda text: to_mermaid_id(text, COMPONENTS_META)

    for md_file in root_dir.rglob("*.md"):
        if any(part in str(md_file) for part in ["README", "_templates", "architecture"]):
            continue

        data = parse_markdown_frontmatter(md_file)
        if not data or 'service_name' not in data:
            continue

        service_id = id_converter(data['service_name'])
        if service_id:
            discovered_ids.add(service_id)

        for item in data.get('inputs', []):
            source_name = item.get('source')
            source_id = id_converter(source_name)
            # --- 変更点 4: IDが空でないことを確認 ---
            if source_id and service_id:
                discovered_ids.add(source_id)
                connections.add(f"    {source_id} --> {service_id}")

        for item in data.get('outputs', []):
            target_name = item.get('target')
            target_id = id_converter(target_name)
            if service_id and target_id:
                discovered_ids.add(target_id)
                connections.add(f"    {service_id} --> {target_id}")
    
    # --- 3. Generate Mermaid markdown ---
    mermaid_lines = ["graph LR\n"]

    # Define nodes within their subgraphs
    for subgraph_name, members in SUBGRAPH_STRUCTURE.items():
        mermaid_lines.append(f'    subgraph "{subgraph_name}"')
        if subgraph_name in ["API & Data Ingestion", "Backend Processing", "Storage Layer", "Management & Export"]:
             mermaid_lines.append("        direction TB")
        for member_id in members:
            # --- 変更点 5: discovered_ids（実際に登場したノード）のみを描画 ---
            if member_id in discovered_ids and member_id in COMPONENTS_META:
                meta = COMPONENTS_META[member_id]
                mermaid_lines.append(f'        {member_id}["{meta["icon"]} {meta["label"]}"]')
        mermaid_lines.append("    end\n")

    # Add connections
    if connections:
        mermaid_lines.append("    %% --- Connections ---")
        mermaid_lines.extend(sorted(list(connections)))
    
    # Add styling
    mermaid_lines.append("\n    %% --- Styling ---")
    mermaid_lines.append("    style \"External Actors\" fill:#e3f2fd,stroke:#333")
    mermaid_lines.append("    style \"Mobile Client\" fill:#e8f5e9,stroke:#333")
    mermaid_lines.append("    classDef storage fill:#f8d7da,stroke:#721c24")
    mermaid_lines.append("    class MinIO,PostgreSQL storage")
    mermaid_lines.append("    classDef queue fill:#fff3cd,stroke:#856404")
    mermaid_lines.append("    class RawDataExchange,ProcessingQueue,AnalysisQueue queue")
    
    # --- 4. Write the final markdown file ---
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_text = f"""# Data Flow Diagram
(This file is auto-generated by a script. Do not edit manually.)

```mermaid
{"\n".join(mermaid_lines)}
```
"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output_text)

    print(f"Diagram successfully generated at {output_file}")

if __name__ == "__main__":
    main()
