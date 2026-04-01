"""osop.render — Render OSOP workflow as Mermaid or ASCII diagram."""

from __future__ import annotations

from typing import Any

from .common import load_yaml


def render(
    content: str | None = None,
    file_path: str | None = None,
    format: str = "mermaid",
    direction: str = "TB",
) -> dict[str, Any]:
    """Render an OSOP workflow as a diagram."""
    raw, parsed = load_yaml(content, file_path)

    nodes = parsed.get("nodes", [])
    edges = parsed.get("edges", [])

    if format == "mermaid":
        return {"format": "mermaid", "diagram": _to_mermaid(nodes, edges, direction)}
    elif format == "ascii":
        return {"format": "ascii", "diagram": _to_ascii(nodes, edges)}
    else:
        return {"error": f"Unsupported format: {format}. Use 'mermaid' or 'ascii'."}


def _to_mermaid(nodes: list, edges: list, direction: str) -> str:
    lines = [f"graph {direction}"]

    # Node shapes by type
    shape_map = {
        "human": ("([", "])"),       # Stadium
        "agent": ("{{", "}}"),       # Hexagon
        "gateway": ("{", "}"),       # Diamond
        "event": (">", "]"),         # Flag
        "data": ("[(", ")]"),        # Cylinder
        "db": ("[(", ")]"),          # Cylinder
    }

    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "?")
        label = node.get("name", nid)
        ntype = node.get("type", "system")
        left, right = shape_map.get(ntype, ("[", "]"))
        lines.append(f"    {nid}{left}\"{label}\"{right}")

    # Edge modes to Mermaid arrows
    arrow_map = {
        "sequential": "-->",
        "conditional": "-.->",
        "parallel": "==>",
        "fallback": "-. fallback .->",
        "error": "-. error .->",
        "loop": "-->|loop|",
        "compensation": "-. undo .->",
    }

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("from", "?")
        tgt = edge.get("to", "?")
        mode = edge.get("mode", "sequential")
        label = edge.get("label") or edge.get("when") or ""
        arrow = arrow_map.get(mode, "-->")

        if label and "|" not in arrow:
            lines.append(f"    {src} {arrow}|{label}| {tgt}")
        else:
            lines.append(f"    {src} {arrow} {tgt}")

    return "\n".join(lines)


def _to_ascii(nodes: list, edges: list) -> str:
    lines = []
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "?")
        label = node.get("name", nid)
        ntype = node.get("type", "?")
        lines.append(f"  [{ntype}] {nid}: {label}")

    lines.append("")
    lines.append("  Edges:")
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        mode = edge.get("mode", "sequential")
        label = edge.get("label", "")
        suffix = f" ({label})" if label else ""
        lines.append(f"    {edge.get('from')} --{mode}--> {edge.get('to')}{suffix}")

    return "\n".join(lines)
