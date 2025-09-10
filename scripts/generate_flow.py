# ... existing code ...
def main():
    root_dir = Path(__file__).parent.parent
    architecture_dir = root_dir / "architecture"
# ... existing code ...
    output_image_file = architecture_dir / "data-flow-diagram.svg"
    temp_mermaid_file = architecture_dir / "temp_diagram.mmd"

    
    COMPONENTS_META = {
        'User': {"label": "User", "icon": "fa:fa-user"},
# ... existing code ...
        'ProcessorService': {"label": "Processor Service", "icon": "fa:fa-cogs"},
        'RealtimeAnalyzerService': {"label": "Realtime Analyzer", "icon": "fa:fa-chart-line"},
        # --- 変更点: 未定義だったAPIサーバーを追加 ---
        'APIServer': {"label": "External API", "icon": "fa:fa-cloud"},
        'MinIO': {"label": "MinIO<br>(Object Storage)", "icon": "fa:fa-database"},
        'PostgreSQL': {"label": "PostgreSQL<br>(Metadata DB)", "icon": "fa:fa-database"},
        'SessionManagerService': {"label": "Session Manager", "icon": "fa:fa-tasks"},
# ... existing code ...
        'DataLinkageWorker': {"label": "Async Task Queue<br>(DataLinker)", "icon": "fa:fa-rocket"}
    }
    
    SUBGRAPH_STRUCTURE = {
        "External Actors": ['User', 'Firmware_BLE'],
        # --- 変更点: APIサーバー用のサブグラフを追加 ---
        "External Services": ['APIServer'],
        "Mobile Client": ['SmartphoneApp'],
        "API & Data Ingestion": ['CollectorService', 'RawDataExchange', 'ProcessingQueue', 'AnalysisQueue'],
        "Backend Processing": ['ProcessorService', 'RealtimeAnalyzerService'],
# ... existing code ...
# ... existing code ...
    try:
        subprocess.run(
            [
                "mmdc",
                "-i", str(temp_mermaid_file),
                "-o", str(output_image_file),
                "-b", "transparent", # 背景を透過に
                # --- 変更点: puppeteer設定ファイルを読み込ませる ---
                "-p", str(root_dir / "scripts" / "puppeteer-config.json"),
            ],
            check=True,
            capture_output=True,
# ... existing code ...
