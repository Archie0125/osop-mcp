"""OSOP workflow diff — compare two OSOP workflows structurally."""

from __future__ import annotations

from typing import Any

from .common import load_yaml


def diff_workflows(
    content_a: str | None = None,
    file_path_a: str | None = None,
    content_b: str | None = None,
    file_path_b: str | None = None,
) -> dict[str, Any]:
    """Compare two OSOP workflows and return structural differences.

    Returns added/removed/changed nodes, edges, and metadata.
    """
    _, data_a = load_yaml(content=content_a, file_path=file_path_a)
    _, data_b = load_yaml(content=content_b, file_path=file_path_b)

    # Compare metadata
    meta_changes: list[dict[str, Any]] = []
    meta_keys = ["name", "description", "version", "osop_version", "id", "tags", "timeout_sec"]
    for key in meta_keys:
        val_a = data_a.get(key)
        val_b = data_b.get(key)
        if val_a != val_b:
            meta_changes.append({"field": key, "before": val_a, "after": val_b})

    # Compare nodes
    nodes_a = {n["id"]: n for n in data_a.get("nodes", []) if isinstance(n, dict) and "id" in n}
    nodes_b = {n["id"]: n for n in data_b.get("nodes", []) if isinstance(n, dict) and "id" in n}

    added_nodes = [nodes_b[nid] for nid in nodes_b if nid not in nodes_a]
    removed_nodes = [nodes_a[nid] for nid in nodes_a if nid not in nodes_b]
    changed_nodes: list[dict[str, Any]] = []
    for nid in nodes_a:
        if nid in nodes_b and nodes_a[nid] != nodes_b[nid]:
            changes: dict[str, Any] = {"id": nid}
            for key in set(list(nodes_a[nid].keys()) + list(nodes_b[nid].keys())):
                if key == "id":
                    continue
                va = nodes_a[nid].get(key)
                vb = nodes_b[nid].get(key)
                if va != vb:
                    changes[key] = {"before": va, "after": vb}
            changed_nodes.append(changes)

    # Compare edges
    def _edge_key(e: dict) -> str:
        return f"{e.get('from', '')} -> {e.get('to', '')}"

    edges_a = {_edge_key(e): e for e in data_a.get("edges", []) if isinstance(e, dict)}
    edges_b = {_edge_key(e): e for e in data_b.get("edges", []) if isinstance(e, dict)}

    added_edges = [edges_b[ek] for ek in edges_b if ek not in edges_a]
    removed_edges = [edges_a[ek] for ek in edges_a if ek not in edges_b]
    changed_edges: list[dict[str, Any]] = []
    for ek in edges_a:
        if ek in edges_b and edges_a[ek] != edges_b[ek]:
            changes = {"edge": ek}
            for key in set(list(edges_a[ek].keys()) + list(edges_b[ek].keys())):
                va = edges_a[ek].get(key)
                vb = edges_b[ek].get(key)
                if va != vb:
                    changes[key] = {"before": va, "after": vb}
            changed_edges.append(changes)

    total_changes = (
        len(meta_changes)
        + len(added_nodes) + len(removed_nodes) + len(changed_nodes)
        + len(added_edges) + len(removed_edges) + len(changed_edges)
    )

    return {
        "identical": total_changes == 0,
        "total_changes": total_changes,
        "metadata": meta_changes,
        "nodes": {
            "added": added_nodes,
            "removed": removed_nodes,
            "changed": changed_nodes,
        },
        "edges": {
            "added": added_edges,
            "removed": removed_edges,
            "changed": changed_edges,
        },
        "summary": {
            "workflow_a": {"nodes": len(nodes_a), "edges": len(edges_a)},
            "workflow_b": {"nodes": len(nodes_b), "edges": len(edges_b)},
        },
    }
