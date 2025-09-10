import re
import yaml
from pathlib import Path
import unicodedata

# --- 名称の揺れを吸収するためのマッピング ---
NAME_TO_ID_MAP = {
    "（データ紐付けワーカー）": "DataLinkageWorker",
    "非同期タスクキュー (例: Celery)": "DataLinkageWorker",
    "Async Task Queue (DataLinker)": "DataLinkageWorker",
    "Firmware (ESP32)": "Firmware_BLE",
    "ファームウェア (BLE)": "Firmware_BLE",
    "スマートフォンアプリ": "SmartphoneApp",
    "Smartphone App": "SmartphoneApp",
    "Collectorサービス": "CollectorService",
    "Collector Service": "CollectorService",
    "Processorサービス": "ProcessorService",
    "Processor Service": "ProcessorService",
    "Realtime Analyzerサービス": "RealtimeAnalyzerService",
    "Realtime Analyzer Service": "RealtimeAnalyzerService",
    "Session Managerサービス": "SessionManagerService",
    "Session Manager Service": "SessionManagerService",
    "BIDS Exporterサービス": "BIDSExporterService",
    "BIDS Exporter Service": "BIDSExporterService",
    "MinIO (オブジェクトストレージ)": "MinIO",
    "PostgreSQL": "PostgreSQL",
    "PostgreSQL Database": "PostgreSQL",
    "ユーザー": "User",
    "ユーザー (via API Call)": "User",
    "RabbitMQ (Fanout Exchange: raw_data_exchange)": "RawDataExchange",
    "RabbitMQ (processing_queue)": "ProcessingQueue",
    "RabbitMQ (analysis_queue)": "AnalysisQueue",
}


def to_mermaid_id(text, components_meta):
    """
    文字列をMermaid.jsの有効なノードIDに変換します。
    """
    if not isinstance(text, str):
        return ""

    original_text = text
    normalized_text = unicodedata.normalize('NFKC', text).strip()

    if normalized_text in NAME_TO_ID_MAP:
        return NAME_TO_ID_MAP[normalized_text]

    for component_id, meta in components_meta.items():
        label_without_br = meta.get("label", "").replace("<br>", " ")
        if normalized_text == label_without_br or normalized_text == component_id:
            return component_id
            
    text_without_parens = re.sub(r'[\(（].*?[\)）]', '', normalized_text).strip()
    if text_without_parens in NAME_TO_ID_MAP:
        return NAME_TO_ID_MAP[text_without_parens]

    print(f"Warning: Could not find a matching ID for '{original_text}'. It will be skipped.")
    return ""


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
    if not match:
        return None
        
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        print(f"Error parsing YAML in {file_path}: {e}")
        return None

def main():
    root_dir = Path(__file__).parent.parent
    output_file = root_dir / "architecture" / "02-data-flow.md"
    
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

    connections = set()
    discovered_ids = set()

    for md_file in root_dir.rglob("*.md"):
        if any(part in str(md_file) for part in ["README", "_templates", "architecture"]):
            continue

        data = parse_markdown_frontmatter(md_file)
        if not data:
            continue
        
        if 'exchange_fanout' in data:
            fanout_data = data['exchange_fanout']
            exchange_name = fanout_data.get('name')
            exchange_id = to_mermaid_id(exchange_name, COMPONENTS_META)
            if exchange_id:
                discovered_ids.add(exchange_id)
                for target_queue in fanout_data.get('outputs', []):
                    queue_id = to_mermaid_id(target_queue, COMPONENTS_META)
                    if queue_id:
                        discovered_ids.add(queue_id)
                        # --- 変更点: セミコロンを追加 ---
                        connections.add(f"    {exchange_id} --> {queue_id};")
            continue

        if 'service_name' not in data:
            continue

        service_id = to_mermaid_id(data['service_name'], COMPONENTS_META)
        if service_id:
            discovered_ids.add(service_id)

        for item in data.get('inputs', []):
            source_name = item.get('source')
            source_id = to_mermaid_id(source_name, COMPONENTS_META)
            if source_id and service_id:
                discovered_ids.add(source_id)
                # --- 変更点: セミコロンを追加 ---
                connections.add(f"    {source_id} --> {service_id};")

        for item in data.get('outputs', []):
            target_name = item.get('target')
            target_id = to_mermaid_id(target_name, COMPONENTS_META)
            if service_id and target_id:
                discovered_ids.add(target_id)
                # --- 変更点: セミコロンを追加 ---
                connections.add(f"    {service_id} --> {target_id};")
    
    mermaid_lines = ["graph LR\n"]

    for subgraph_name, members in SUBGRAPH_STRUCTURE.items():
        drawable_members = [m for m in members if m in discovered_ids]
        if not drawable_members:
            continue

        mermaid_lines.append(f'    subgraph "{subgraph_name}"')
        if subgraph_name in ["API & Data Ingestion", "Backend Processing", "Storage Layer", "Management & Export"]:
             mermaid_lines.append("        direction TB")
        for member_id in drawable_members:
            if member_id in COMPONENTS_META:
                meta = COMPONENTS_META[member_id]
                mermaid_lines.append(f'        {member_id}["{meta["icon"]} {meta["label"]}"];')
        mermaid_lines.append("    end\n")

    if connections:
        mermaid_lines.append("    %% --- Connections ---")
        mermaid_lines.extend(sorted(list(connections)))
        mermaid_lines.append("")
    
    mermaid_lines.append("    %% --- Styling ---")
    mermaid_lines.append("    style \"External Actors\" fill:#e3f2fd,stroke:#333;")
    mermaid_lines.append("    style \"Mobile Client\" fill:#e8f5e9,stroke:#333;")
    mermaid_lines.append("    classDef storage fill:#f8d7da,stroke:#721c24;")
    mermaid_lines.append("    class MinIO,PostgreSQL storage;")
    mermaid_lines.append("    classDef queue fill:#fff3cd,stroke:#856404;")
    mermaid_lines.append("    class RawDataExchange,ProcessingQueue,AnalysisQueue queue;")
    
    mermaid_content = "\n".join(mermaid_lines)
    
    output_text = f"""# Data Flow Diagram
(This file is auto-generated by a script. Do not edit manually.)

```mermaid
{mermaid_content}
```
"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output_text)

    print(f"Diagram successfully generated at {output_file}")

if __name__ == "__main__":
    main()

