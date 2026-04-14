"""OSOP → Notion converter.

Converts .osop YAML into Notion database-ready structures.
Returns Notion API payloads that can be used with the Notion REST API.
"""

from __future__ import annotations

import re
from typing import Any

from .common import load_yaml


# Node type → Notion select color
TYPE_COLORS = {
    "human": "blue", "agent": "purple", "api": "green", "cli": "yellow",
    "db": "default", "system": "gray", "cicd": "orange", "mcp": "blue",
    "infra": "green", "data": "green", "git": "red", "docker": "blue",
    "event": "pink",
}


def _parse_nodes_edges(data: dict) -> tuple[list[dict], list[dict]]:
    """Extract nodes and edges from parsed OSOP data."""
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    return nodes, edges


def _compute_order(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Topological sort → order index per node."""
    in_deg: dict[str, int] = {n["id"]: 0 for n in nodes}
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    for e in edges:
        f, t = e.get("from", ""), e.get("to", "")
        if f in adj and t in in_deg:
            adj[f].append(t)
            in_deg[t] = in_deg.get(t, 0) + 1

    queue = [nid for nid, deg in in_deg.items() if deg == 0]
    order: dict[str, int] = {}
    idx = 1
    while queue:
        nid = queue.pop(0)
        order[nid] = idx
        idx += 1
        for child in adj.get(nid, []):
            in_deg[child] -= 1
            if in_deg[child] == 0:
                queue.append(child)

    # Assign remaining (cycles)
    for n in nodes:
        if n["id"] not in order:
            order[n["id"]] = idx
            idx += 1

    return order


def _get_dependencies(node_id: str, edges: list[dict]) -> list[str]:
    """Get IDs of nodes that must complete before this node."""
    return [e["from"] for e in edges if e.get("to") == node_id]


def osop_to_notion(
    content: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Convert .osop YAML to Notion-ready database structure.

    Returns:
        dict with:
        - database_schema: Notion database schema (properties definition)
        - pages: list of Notion page payloads (one per workflow node)
        - workflow_meta: workflow-level metadata
    """
    data = load_yaml(content=content, file_path=file_path)
    nodes, edges = _parse_nodes_edges(data)
    order = _compute_order(nodes, edges)

    # Database schema suggestion
    database_schema = {
        "Name": {"title": {}},
        "Type": {
            "select": {
                "options": [
                    {"name": t, "color": TYPE_COLORS.get(t, "default")}
                    for t in sorted(set(n.get("type", "system") for n in nodes))
                ]
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Not Started", "color": "default"},
                    {"name": "In Progress", "color": "blue"},
                    {"name": "Completed", "color": "green"},
                    {"name": "Blocked", "color": "red"},
                ]
            }
        },
        "Order": {"number": {"format": "number"}},
        "Description": {"rich_text": {}},
        "Dependencies": {"rich_text": {}},
        "Timeout": {"number": {"format": "number"}},
    }

    # Build page payloads
    pages = []
    for node in nodes:
        nid = node.get("id", "")
        deps = _get_dependencies(nid, edges)
        dep_str = ", ".join(deps) if deps else "None"

        page = {
            "properties": {
                "Name": {"title": [{"text": {"content": node.get("name", nid)}}]},
                "Type": {"select": {"name": node.get("type", "system")}},
                "Status": {"select": {"name": "Not Started"}},
                "Order": {"number": order.get(nid, 0)},
                "Description": {
                    "rich_text": [{"text": {"content": node.get("description", node.get("purpose", ""))}}]
                },
                "Dependencies": {"rich_text": [{"text": {"content": dep_str}}]},
            }
        }

        timeout = node.get("timeout_sec")
        if timeout:
            page["properties"]["Timeout"] = {"number": timeout}

        pages.append(page)

    # Workflow metadata
    workflow_meta = {
        "name": data.get("name", data.get("id", "Untitled")),
        "description": data.get("description", ""),
        "id": data.get("id", ""),
        "version": data.get("osop_version", "1.0"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "tags": data.get("tags", []),
    }

    return {
        "database_schema": database_schema,
        "pages": pages,
        "workflow_meta": workflow_meta,
        "notion_api_hint": "POST https://api.notion.com/v1/databases with database_schema, then POST https://api.notion.com/v1/pages for each page.",
    }
