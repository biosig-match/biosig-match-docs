import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from graphviz import Digraph

EXCLUDED_DIR_KEYWORDS = {"README", "_templates", "architecture"}

COMPONENT_COLORS = {
    "service": "#e8f0fe",
    "queue": "#fff3cd",
    "exchange": "#fdebd0",
    "storage": "#e8f5e9",
    "database": "#f8d7da",
    "client": "#e3f2fd",
    "hardware": "#ede7f6",
    "other": "#ffffff",
}


def parse_markdown_frontmatter(file_path: Path) -> Optional[Dict[str, Any]]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", ascii_text).strip("_")
    return cleaned or "node"


def make_node_id(label: str, existing: Dict[str, str]) -> str:
    key = label.lower().strip()
    if key in existing:
        return existing[key]

    base = slugify(label)
    candidate = base or "node"
    suffix = 1
    while candidate in existing.values():
        suffix += 1
        candidate = f"{base}_{suffix}"

    existing[key] = candidate
    return candidate


def extract_entries(data: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = data.get(key)
    if not value:
        return []
    if isinstance(value, list):
        entries: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                entries.append(item)
            elif isinstance(item, str):
                entries.append({"text": item})
        return entries
    return []


def build_label(data_format: Optional[str], schema: Optional[str]) -> str:
    parts = []
    if data_format:
        parts.append(str(data_format).strip())
    if schema:
        parts.append(str(schema).strip())
    return "\n".join(parts)


def main() -> None:
    root_dir = Path(__file__).parent.parent
    architecture_dir = root_dir / "architecture"
    architecture_dir.mkdir(exist_ok=True)

    output_md_file = architecture_dir / "02_data-flow.md"
    output_filename = "data-flow-diagram"

    name_to_id: Dict[str, str] = {}
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Tuple[str, str, Dict[str, str]]] = []

    docs = sorted(root_dir.rglob("*.md"))

    for md_file in docs:
        if any(part in md_file.parts for part in EXCLUDED_DIR_KEYWORDS):
            continue

        data = parse_markdown_frontmatter(md_file)
        if not data:
            continue

        service_name = data.get("service_name")
        component_type = str(data.get("component_type", "other") or "other").lower()
        description = data.get("description")

        this_node_id: Optional[str] = None
        if service_name:
            this_node_id = make_node_id(service_name, name_to_id)
            nodes.setdefault(
                this_node_id,
                {
                    "label": service_name,
                    "component_type": component_type,
                    "description": description or "",
                },
            )
        elif data.get("exchange_fanout"):
            # 後方互換: 古い形式の front matter を許容
            exchange = data["exchange_fanout"]
            name = exchange.get("name")
            if name:
                component_type = "exchange"
                this_node_id = make_node_id(name, name_to_id)
                nodes.setdefault(
                    this_node_id,
                    {
                        "label": name,
                        "component_type": component_type,
                        "description": exchange.get("description", ""),
                    },
                )
            outputs = exchange.get("outputs", [])
            for target in outputs:
                target_name = str(target)
                target_id = make_node_id(target_name, name_to_id)
                nodes.setdefault(
                    target_id,
                    {
                        "label": target_name,
                        "component_type": "other",
                        "description": "",
                    },
                )
                edges.append(
                    (
                        this_node_id,
                        target_id,
                        {
                            "label": "AMQP Message",
                            "tooltip": target_name,
                        },
                    )
                )
            continue

        inputs = extract_entries(data, "inputs")
        outputs = extract_entries(data, "outputs")

        for entry in inputs:
            source_name = entry.get("source") or entry.get("name") or entry.get("text")
            if not source_name:
                continue
            source_name = str(source_name)
            source_id = make_node_id(source_name, name_to_id)
            nodes.setdefault(
                source_id,
                {
                    "label": source_name,
                    "component_type": "other",
                    "description": "",
                },
            )
            if not this_node_id:
                continue
            label = build_label(entry.get("data_format"), entry.get("schema"))
            tooltip = entry.get("schema") or entry.get("data_format") or source_name
            edges.append(
                (
                    source_id,
                    this_node_id,
                    {
                        "label": label,
                        "tooltip": str(tooltip),
                    },
                )
            )

        for entry in outputs:
            target_name = entry.get("target") or entry.get("name") or entry.get("text")
            if not target_name:
                continue
            target_name = str(target_name)
            target_id = make_node_id(target_name, name_to_id)
            nodes.setdefault(
                target_id,
                {
                    "label": target_name,
                    "component_type": "other",
                    "description": "",
                },
            )
            if not this_node_id:
                continue
            label = build_label(entry.get("data_format"), entry.get("schema"))
            tooltip = entry.get("schema") or entry.get("data_format") or target_name
            edges.append(
                (
                    this_node_id,
                    target_id,
                    {
                        "label": label,
                        "tooltip": str(tooltip),
                    },
                )
            )

    dot = Digraph(comment="Data Flow Diagram")
    dot.attr(
        rankdir="LR",
        splines="ortho",
        nodesep="1.5",
        ranksep="3.0",
        label="Interactive Data Flow Diagram",
        labelloc="t",
        fontsize="20",
        overlap="scale",
        sep="+25",
    )

    dot.attr(
        "node",
        shape="box",
        style="rounded,filled",
        fontname="Arial",
        fontsize="12",
    )
    dot.attr("edge", fontname="Arial", fontsize="10")

    for node_id, meta in nodes.items():
        comp_type = meta.get("component_type", "other")
        fillcolor = COMPONENT_COLORS.get(comp_type, COMPONENT_COLORS["other"])
        tooltip = meta.get("description") or meta.get("label")
        dot.node(node_id, label=meta.get("label", node_id), fillcolor=fillcolor, tooltip=tooltip)

    seen_edges = set()
    for source_id, target_id, details in edges:
        if not source_id or not target_id:
            continue
        key = (source_id, target_id, details.get("label"))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        label = details.get("label")
        tooltip = details.get("tooltip")
        kwargs = {"tooltip": tooltip}
        if label:
            kwargs["xlabel"] = label
        dot.edge(source_id, target_id, **kwargs)

    try:
        output_path = architecture_dir / output_filename
        dot.render(output_path, format="svg", cleanup=True)
        print(f"Diagram successfully generated at {output_path}.svg")
    except Exception as error:  # pragma: no cover - graphviz runtime errors
        print(f"Error generating diagram with Graphviz: {error}")
        print("Please ensure Graphviz is installed and accessible in PATH.")
        return

    output_image_file_name = f"{output_filename}.svg"
    output_text = f"""# Data Flow Diagram
(This file is auto-generated by a script. Do not edit manually.)

**Note:** この図はインタラクティブです。ノードやエッジにマウスオーバーすると補足情報が表示されます。

![Data Flow Diagram](./{output_image_file_name})
"""
    output_md_file.write_text(output_text, encoding="utf-8")
    print(f"Markdown file successfully updated at {output_md_file}")


if __name__ == "__main__":  # pragma: no cover
    main()
