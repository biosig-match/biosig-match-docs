import re
import yaml
from pathlib import Path
import unicodedata
import os

def to_mermaid_id(text):
    """
    文字列をMermaid.jsの有効なノードIDに変換します。
    - 日本語文字を正規化します。
    - 問題のある文字をアンダースコアに置換します。
    - 残りの英数字以外の文字を削除します。
    """
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = text.replace('スマートフォンアプリ', 'SmartphoneApp')
    text = text.replace('サービス', 'Service')
    text = text.replace('（データ紐付けワーカー）', 'DataLinkageWorker')
    text = re.sub(r'[\s/,-]+', '_', text)
    text = re.sub(r'[^\w]', '', text)
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
    # Map normalized IDs to their display name and icon
    COMPONENTS_META = {
        'User': {"label": "User", "icon": "fa:fa-user"},
        'Firmware_BLE': {"label": "Firmware (BLE)", "icon": "fa:fa-microchip"},
        'SmartphoneApp': {"label": "Smartphone App", "icon": "fa:fa-mobile-alt"},
        'CollectorService': {"label": "Collector Service", "icon": "fa:fa-server"},
        'RabbitMQ_FanoutExchange_raw_data_exchange': {"label": "RabbitMQ Exchange<br>(raw_data_exchange)", "icon": "fa:fa-exchange"},
        'RabbitMQ_processing_queue': {"label": "Processing Queue", "icon": "fa:fa-inbox"},
        'RabbitMQ_analysis_queue': {"label": "Analysis Queue", "icon": "fa:fa-inbox"},
        'ProcessorService': {"label": "Processor Service", "icon": "fa:fa-cogs"},
        'RealtimeAnalyzerService': {"label": "Realtime Analyzer", "icon": "fa:fa-chart-line"},
        'MinIO_ObjectStorage': {"label": "MinIO<br>(Object Storage)", "icon": "fa:fa-database"},
        'PostgreSQL_Database': {"label": "PostgreSQL<br>(Metadata DB)", "icon": "fa:fa-database"},
        'SessionManagerService': {"label": "Session Manager", "icon": "fa:fa-tasks"},
        'BIDSExporterService': {"label": "BIDS Exporter", "icon": "fa:fa-file-archive"},
        'DataLinkageWorker': {"label": "Async Task Queue<br>(e.g., Celery/DataLinker)", "icon": "fa:fa-rocket"}
    }
    
    SUBGRAPH_STRUCTURE = {
        "External Actors": ['User', 'Firmware_BLE'],
        "Mobile Client": ['SmartphoneApp'],
        "API & Data Ingestion": ['CollectorService', 'RabbitMQ_FanoutExchange_raw_data_exchange', 'RabbitMQ_processing_queue', 'RabbitMQ_analysis_queue'],
        "Backend Processing": ['ProcessorService', 'RealtimeAnalyzerService'],
        "Storage Layer": ['MinIO_ObjectStorage', 'PostgreSQL_Database'],
        "Management & Export": ['SessionManagerService', 'BIDSExporterService', 'DataLinkageWorker']
    }

    # --- 2. Discover connections from .md files ---
    connections = set()
    discovered_ids = set()

    for md_file in root_dir.rglob("*.md"):
        if any(part in str(md_file) for part in ["README", "_templates", "architecture"]):
            continue

        data = parse_markdown_frontmatter(md_file)
        if not data or 'service_name' not in data:
            continue

        service_id = to_mermaid_id(data['service_name'])
        discovered_ids.add(service_id)

        for item in data.get('inputs', []):
            source_name = item.get('source')
            if source_name:
                source_id = to_mermaid_id(source_name)
                discovered_ids.add(source_id)
                connections.add(f"    {source_id} --> {service_id}")

        for item in data.get('outputs', []):
            target_name = item.get('target')
            if target_name:
                target_id = to_mermaid_id(target_name)
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
            if member_id in discovered_ids and member_id in COMPONENTS_META:
                meta = COMPONENTS_META[member_id]
                mermaid_lines.append(f'        {member_id}["{meta["icon"]} {meta["label"]}"]')
        mermaid_lines.append("    end\n")

    # Add connections
    mermaid_lines.append("    %% --- Connections ---")
    mermaid_lines.extend(sorted(list(connections)))
    
    # Add styling
    mermaid_lines.append("\n    %% --- Styling ---")
    mermaid_lines.append("    style \"External Actors\" fill:#e3f2fd,stroke:#333")
    mermaid_lines.append("    style \"Mobile Client\" fill:#e8f5e9,stroke:#333")
    mermaid_lines.append("    classDef storage fill:#f8d7da,stroke:#721c24")
    mermaid_lines.append("    class MinIO_ObjectStorage,PostgreSQL_Database storage")
    mermaid_lines.append("    classDef queue fill:#fff3cd,stroke:#856404")
    mermaid_lines.append("    class RabbitMQ_FanoutExchange_raw_data_exchange,RabbitMQ_processing_queue,RabbitMQ_analysis_queue queue")
    
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

