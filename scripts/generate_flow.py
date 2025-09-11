import re
import yaml
from pathlib import Path
import unicodedata
import sys
from graphviz import Digraph

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
    "MinIO": "MinIO",
    "PostgreSQL": "PostgreSQL",
    "PostgreSQL Database": "PostgreSQL",
    "ユーザー": "User",
    "ユーザー (via API Call)": "User",
    "RabbitMQ (Fanout Exchange: raw_data_exchange)": "RawDataExchange",
    "RabbitMQ (processing_queue)": "ProcessingQueue",
    "RabbitMQ (analysis_queue)": "AnalysisQueue",
    "各種サーバーAPI": "APIServer",
    "ERP検出システム": "APIServer",
}


def to_id(text, components_meta):
    """
    文字列をGraphvizの有効なノードIDに変換します。
    """
    if not isinstance(text, str):
        return ""

    original_text = text
    normalized_text = unicodedata.normalize('NFKC', text).strip()

    if normalized_text in NAME_TO_ID_MAP:
        return NAME_TO_ID_MAP[normalized_text]

    for component_id, meta in components_meta.items():
        label_for_compare = meta.get("label", "").replace("\n", " ")
        if normalized_text == label_for_compare or normalized_text == component_id:
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
    # NOTE: Assuming the script is in a 'scripts' directory or similar. 
    # Adjust if your structure is different.
    if not root_dir.exists() or not any(root_dir.iterdir()):
        root_dir = Path.cwd() # Fallback to current working directory
        
    architecture_dir = root_dir / "architecture"
    architecture_dir.mkdir(exist_ok=True)
    
    output_md_file = architecture_dir / "02_data-flow.md"
    output_filename = "data-flow-diagram"

    COMPONENTS_META = {
        'User': {"label": "User", "description": "System User"},
        'Firmware_BLE': {"label": "Firmware (BLE)", "description": "Data acquisition firmware"},
        'SmartphoneApp': {"label": "Smartphone App", "description": "Mobile client and data relay"},
        'CollectorService': {"label": "Collector Service", "description": "API gateway for raw data ingestion"},
        'RawDataExchange': {"label": "RabbitMQ Exchange\n(raw_data_exchange)", "description": "Fanout exchange for data distribution"},
        'ProcessingQueue': {"label": "Processing Queue", "description": "Queue for data persistence tasks"},
        'AnalysisQueue': {"label": "Analysis Queue", "description": "Queue for real-time analysis tasks"},
        'ProcessorService': {"label": "Processor Service", "description": "Processes and persists raw data"},
        'RealtimeAnalyzerService': {"label": "Realtime Analyzer", "description": "Performs real-time analysis"},
        'APIServer': {"label": "External API", "description": "Third-party or external APIs (e.g., ERP Detection System)"},
        'MinIO': {"label": "MinIO\n(Object Storage)", "description": "Scalable storage for raw data objects"},
        'PostgreSQL': {"label": "PostgreSQL\n(Metadata DB)", "description": "Relational database for all metadata"},
        'SessionManagerService': {"label": "Session Manager", "description": "Manages experiment and session lifecycles"},
        'BIDSExporterService': {"label": "BIDS Exporter", "description": "Exports data in BIDS format"},
        'DataLinkageWorker': {"label": "Async Task Queue\n(DataLinker)", "description": "Asynchronous worker for data linkage"}
    }

    SUBGRAPH_STRUCTURE = {
        "External Actors": ['User', 'Firmware_BLE'],
        "External Services": ['APIServer'],
        "Mobile Client": ['SmartphoneApp'],
        "API & Data Ingestion": ['CollectorService', 'RawDataExchange', 'ProcessingQueue', 'AnalysisQueue'],
        "Backend Processing": ['ProcessorService', 'RealtimeAnalyzerService'],
        "Storage Layer": ['MinIO', 'PostgreSQL'],
        "Management & Export": ['SessionManagerService', 'BIDSExporterService', 'DataLinkageWorker']
    }

    connections = {}
    discovered_ids = set()
    node_descriptions = {}

    for md_file in root_dir.rglob("*.md"):
        if any(part in str(md_file) for part in ["README", "_templates", "architecture"]):
            continue

        data = parse_markdown_frontmatter(md_file)
        if not data:
            continue

        if 'exchange_fanout' in data:
            fanout_data = data['exchange_fanout']
            exchange_name = fanout_data.get('name')
            exchange_id = to_id(exchange_name, COMPONENTS_META)
            if exchange_id:
                discovered_ids.add(exchange_id)
                node_descriptions[exchange_id] = fanout_data.get('description', COMPONENTS_META.get(exchange_id, {}).get('description'))
                outputs_list = fanout_data.get('outputs', [])
                if outputs_list:
                    for item in outputs_list:
                        target_id = to_id(item, COMPONENTS_META)
                        if target_id:
                            discovered_ids.add(target_id)
                            conn_key = (exchange_id, target_id)
                            connections[conn_key] = {
                                "label": "AMQP Message",
                                "tooltip": "Fanout distribution"
                            }
            continue

        if 'service_name' not in data:
            continue

        service_id = to_id(data['service_name'], COMPONENTS_META)
        if service_id:
            discovered_ids.add(service_id)
            node_descriptions[service_id] = data.get('description', COMPONENTS_META.get(service_id, {}).get('description'))

        inputs_list = data.get('inputs')
        if inputs_list:
            for item in inputs_list:
                source_id = to_id(item.get('source'), COMPONENTS_META)
                if source_id and service_id:
                    discovered_ids.add(source_id)
                    conn_key = (source_id, service_id)

                    # --- MODIFICATION: Combine data_format and schema for the edge label ---
                    label_parts = []
                    data_format = item.get('data_format')
                    schema = item.get('schema')
                    if data_format:
                        label_parts.append(data_format)
                    if schema:
                        label_parts.append(schema)
                    
                    connections[conn_key] = {
                        "label": "\n".join(label_parts),
                        "tooltip": f"Schema: {item.get('schema', 'N/A')}"
                    }
                    # --- END MODIFICATION ---

        outputs_list = data.get('outputs')
        if outputs_list:
            for item in outputs_list:
                target_id = to_id(item.get('target'), COMPONENTS_META)
                if service_id and target_id:
                    discovered_ids.add(target_id)
                    conn_key = (service_id, target_id)
                    if conn_key not in connections:
                        # --- MODIFICATION: Combine data_format and schema for the edge label ---
                        label_parts = []
                        data_format = item.get('data_format')
                        schema = item.get('schema')
                        if data_format:
                            label_parts.append(data_format)
                        if schema:
                            label_parts.append(schema)

                        connections[conn_key] = {
                            "label": "\n".join(label_parts),
                            "tooltip": f"Schema: {item.get('schema', 'N/A')}"
                        }
                        # --- END MODIFICATION ---

    # Graphvizオブジェクトの作成
    dot = Digraph(comment='Data Flow Diagram')
    
    dot.attr(
        rankdir='LR', 
        splines='ortho',
        nodesep='1.5',
        ranksep='3.5',
        label='Interactive Data Flow Diagram', 
        labelloc='t', 
        fontsize='20',
        overlap='scale',
        sep='+25'
    )
    
    dot.attr('node', shape='box', style='rounded,filled', fontname='Arial', fontsize='12', width='2.5', height='1.2', fixedsize='true')
    dot.attr('edge', fontname='Arial', fontsize='10')

    # サブグラフ(クラスター)とノードの定義
    for i, (subgraph_name, members) in enumerate(SUBGRAPH_STRUCTURE.items()):
        drawable_members = [m for m in members if m in discovered_ids]
        if not drawable_members:
            continue

        with dot.subgraph(name=f'cluster_{i}') as c:
            c.attr(label=subgraph_name, style='rounded,filled', color='#eeeeee', fontcolor='black', fontsize='16')

            for member_id in drawable_members:
                if member_id in COMPONENTS_META:
                    meta = COMPONENTS_META[member_id]
                    fillcolor = 'white'
                    if 'Storage' in subgraph_name or 'DB' in meta['label']:
                        fillcolor = '#f8d7da'
                    elif 'Queue' in meta['label'] or 'Exchange' in meta['label']:
                        fillcolor = '#fff3cd'
                    elif 'External' in subgraph_name:
                        fillcolor = '#e3f2fd'
                    elif 'Mobile' in subgraph_name:
                        fillcolor = '#e8f5e9'

                    node_tooltip = node_descriptions.get(member_id, meta.get('description', 'No description available.'))
                    c.node(member_id, label=meta['label'], fillcolor=fillcolor, tooltip=node_tooltip)

    # 接続とツールチップの描画
    for (source, target), details in connections.items():
        dot.edge(source, target, xlabel=details.get('label'), tooltip=details.get('tooltip'), labelfontsize='9')

    # SVGファイルの生成
    try:
        output_path = architecture_dir / output_filename
        dot.render(output_path, format='svg', cleanup=True)
        print(f"Diagram successfully generated at {output_path}.svg")
    except Exception as e:
        print(f"Error generating diagram with Graphviz: {e}", file=sys.stderr)
        print("Please ensure Graphviz is installed and in your system's PATH.", file=sys.stderr)
        sys.exit(1)

    # Markdownファイルの更新
    output_image_file_name = f"{output_filename}.svg"
    output_text = f"""# Data Flow Diagram
(This file is auto-generated by a script. Do not edit manually.)

**Note:** This is an interactive diagram. Hover over components and connection lines to see more details.

![Data Flow Diagram](./{output_image_file_name})
"""
    with open(output_md_file, 'w', encoding='utf-8') as f:
        f.write(output_text)

    print(f"Markdown file successfully updated at {output_md_file}")


if __name__ == "__main__":
    main()
