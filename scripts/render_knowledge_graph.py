#!/usr/bin/env python3
"""Render a compact, GitHub-safe overview from Graphify's graph.json."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

SOURCE_SUFFIXES = (".py", ".rs", ".toml")
RELATION_COLORS = {
    "calls": "#2E86AB",
    "imports": "#F18F01",
    "imports_from": "#F18F01",
    "contains": "#6C7A89",
    "method": "#4CAF50",
    "references": "#9C6ADE",
    "uses": "#E05A47",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", default="graphify-out/graph.json")
    parser.add_argument("--output", default="docs/knowledge-graph.svg")
    parser.add_argument("--top", type=int, default=24)
    return parser.parse_args()


def short_label(node: dict[str, object]) -> str:
    label = str(node.get("label") or node.get("id") or "unknown")
    source = str(node.get("source_file") or "")
    if label.endswith((".py", ".rs", ".toml")) and source:
        label = source
    if len(label) > 36:
        label = f"{label[:33]}…"
    return label


def main() -> None:
    args = parse_args()
    graph_path = Path(args.graph)
    output_path = Path(args.output)
    data = json.loads(graph_path.read_text(encoding="utf-8"))

    nodes = {
        str(node["id"]): node
        for node in data["nodes"]
        if str(node.get("source_file") or "").endswith(SOURCE_SUFFIXES)
    }
    edges = [
        edge
        for edge in data["links"]
        if str(edge["source"]) in nodes and str(edge["target"]) in nodes
    ]

    degree: Counter[str] = Counter()
    for edge in edges:
        degree[str(edge["source"])] += 1
        degree[str(edge["target"])] += 1

    selected = [node_id for node_id, _ in degree.most_common(args.top)]
    selected_set = set(selected)
    selected_edges = [
        edge
        for edge in edges
        if str(edge["source"]) in selected_set
        and str(edge["target"]) in selected_set
        and str(edge.get("relation")) not in {"contains", "method"}
    ]

    width, height = 1200, 820
    left_x, right_x = 300, 900
    top_y, row_gap = 150, 54
    positions: dict[str, tuple[int, int]] = {}
    for index, node_id in enumerate(selected):
        column = index % 2
        row = index // 2
        positions[node_id] = (left_x if column == 0 else right_x, top_y + row * row_gap)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>",
        ".title{font:700 28px system-ui,sans-serif;fill:#F5F6FA}.subtitle{font:15px system-ui,sans-serif;fill:#AAB4C3}",
        ".node{fill:#252B3B;stroke:#70839D;stroke-width:1.5}.label{font:12px system-ui,sans-serif;fill:#F5F6FA}.degree{font:11px system-ui,sans-serif;fill:#AAB4C3}",
        ".edge{fill:none;stroke-width:1.5;opacity:.38}",
        "</style>",
        '<rect width="100%" height="100%" rx="18" fill="#1A1F2E"/>',
        '<text x="54" y="58" class="title">HemaFrag-Diagnostics knowledge graph</text>',
        f'<text x="54" y="88" class="subtitle">Graphify code graph · {len(nodes):,} code nodes · {len(edges):,} code relationships · top {len(selected)} hubs shown</text>',
    ]

    for edge in selected_edges:
        source, target = str(edge["source"]), str(edge["target"])
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        relation = str(edge.get("relation") or "related")
        color = RELATION_COLORS.get(relation, "#70839D")
        lines.append(
            f'<path class="edge" stroke="{color}" d="M{x1},{y1} C600,{y1} 600,{y2} {x2},{y2}"><title>{html.escape(relation)}</title></path>'
        )

    for node_id in selected:
        node = nodes[node_id]
        x, y = positions[node_id]
        label = html.escape(short_label(node))
        source = html.escape(str(node.get("source_file") or ""))
        lines.extend(
            [
                f'<rect class="node" x="{x - 220}" y="{y - 19}" width="440" height="38" rx="9"><title>{source}</title></rect>',
                f'<text x="{x - 205}" y="{y + 4}" class="label">{label}</text>',
                f'<text x="{x + 175}" y="{y + 4}" text-anchor="end" class="degree">{degree[node_id]}</text>',
            ]
        )

    legend_y = height - 32
    legend_x = 54
    for relation, color in list(RELATION_COLORS.items())[:6]:
        lines.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>')
        lines.append(f'<text x="{legend_x + 31}" y="{legend_y + 4}" class="degree">{relation}</text>')
        legend_x += 150

    lines.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_path} from {len(nodes):,} nodes and {len(edges):,} edges")


if __name__ == "__main__":
    main()
