"""OSOP diff — compare workflows (.osop) or execution logs (.osoplog)."""

from __future__ import annotations

from typing import Any

import yaml

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


# ---------------------------------------------------------------------------
# Execution log diff (.osoplog)
# ---------------------------------------------------------------------------

def _load_log(content: str | None = None, file_path: str | None = None) -> dict:
    """Load an .osoplog.yaml file."""
    if content:
        data = yaml.safe_load(content)
    elif file_path:
        from pathlib import Path
        raw = Path(file_path).expanduser().resolve().read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    else:
        raise ValueError("Either content or file_path required")
    if not isinstance(data, dict):
        raise ValueError("osoplog must be a YAML mapping")
    return data


def _fmt_duration(ms: int | float) -> str:
    """Format milliseconds as human-readable."""
    if ms < 1000:
        return f"{int(ms)}ms"
    if ms < 60000:
        return f"{ms/1000:.1f}s"
    if ms < 3600000:
        return f"{ms/60000:.1f}m"
    return f"{ms/3600000:.1f}h"


def _pct_change(old: float, new: float) -> str:
    """Format percentage change."""
    if old == 0:
        return "+new" if new > 0 else "same"
    pct = ((new - old) / old) * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.0f}%"


def diff_logs(
    content_a: str | None = None,
    file_path_a: str | None = None,
    content_b: str | None = None,
    file_path_b: str | None = None,
) -> dict[str, Any]:
    """Compare two .osoplog execution logs.

    Returns per-node duration/cost/status deltas and aggregate changes.
    """
    log_a = _load_log(content=content_a, file_path=file_path_a)
    log_b = _load_log(content=content_b, file_path=file_path_b)

    # Build node record maps by node_id
    def _node_map(log: dict) -> dict[str, dict]:
        records = log.get("node_records", [])
        nm: dict[str, dict] = {}
        for r in records:
            if isinstance(r, dict) and r.get("node_id"):
                nm[r["node_id"]] = r
        return nm

    nodes_a = _node_map(log_a)
    nodes_b = _node_map(log_b)

    all_ids = sorted(set(list(nodes_a.keys()) + list(nodes_b.keys())))

    # Per-node comparison
    node_diffs: list[dict] = []
    added_nodes: list[str] = []
    removed_nodes: list[str] = []

    for nid in all_ids:
        a = nodes_a.get(nid)
        b = nodes_b.get(nid)

        if a and not b:
            removed_nodes.append(nid)
            node_diffs.append({
                "node_id": nid,
                "change": "removed",
                "node_type": a.get("node_type", "?"),
            })
            continue
        if b and not a:
            added_nodes.append(nid)
            node_diffs.append({
                "node_id": nid,
                "change": "added",
                "node_type": b.get("node_type", "?"),
            })
            continue

        # Both exist: compare
        dur_a = a.get("duration_ms", 0) or 0
        dur_b = b.get("duration_ms", 0) or 0
        cost_a = a.get("cost_usd", 0) or 0
        cost_b = b.get("cost_usd", 0) or 0

        # Extract cost from ai_metadata if not at top level
        if cost_a == 0 and a.get("ai_metadata"):
            ai = a["ai_metadata"]
            tokens = (ai.get("prompt_tokens", 0) or 0) + (ai.get("completion_tokens", 0) or 0)
            cost_a = tokens * 0.005 / 1000  # rough estimate

        if cost_b == 0 and b.get("ai_metadata"):
            ai = b["ai_metadata"]
            tokens = (ai.get("prompt_tokens", 0) or 0) + (ai.get("completion_tokens", 0) or 0)
            cost_b = tokens * 0.005 / 1000

        status_a = a.get("status", "?")
        status_b = b.get("status", "?")

        diff_entry: dict[str, Any] = {
            "node_id": nid,
            "change": "modified" if (dur_a != dur_b or cost_a != cost_b or status_a != status_b) else "unchanged",
            "node_type": a.get("node_type") or b.get("node_type", "?"),
            "duration": {
                "a": dur_a, "b": dur_b,
                "a_fmt": _fmt_duration(dur_a), "b_fmt": _fmt_duration(dur_b),
                "delta_ms": dur_b - dur_a,
                "delta_pct": _pct_change(dur_a, dur_b),
            },
            "cost": {
                "a": round(cost_a, 6), "b": round(cost_b, 6),
                "delta": round(cost_b - cost_a, 6),
                "delta_pct": _pct_change(cost_a, cost_b),
            },
            "status": {
                "a": status_a, "b": status_b,
                "changed": status_a != status_b,
            },
        }
        node_diffs.append(diff_entry)

    # Aggregates
    total_dur_a = log_a.get("duration_ms", 0) or 0
    total_dur_b = log_b.get("duration_ms", 0) or 0
    total_cost_a = sum((nodes_a.get(nid, {}).get("cost_usd", 0) or 0) for nid in nodes_a)
    total_cost_b = sum((nodes_b.get(nid, {}).get("cost_usd", 0) or 0) for nid in nodes_b)

    status_a_global = log_a.get("status", "?")
    status_b_global = log_b.get("status", "?")

    modified = sum(1 for d in node_diffs if d["change"] == "modified")
    unchanged = sum(1 for d in node_diffs if d["change"] == "unchanged")

    return {
        "log_a": {
            "workflow_id": log_a.get("workflow_id", "?"),
            "run_id": log_a.get("run_id", "?"),
            "status": status_a_global,
            "duration_ms": total_dur_a,
            "duration_fmt": _fmt_duration(total_dur_a),
            "nodes": len(nodes_a),
        },
        "log_b": {
            "workflow_id": log_b.get("workflow_id", "?"),
            "run_id": log_b.get("run_id", "?"),
            "status": status_b_global,
            "duration_ms": total_dur_b,
            "duration_fmt": _fmt_duration(total_dur_b),
            "nodes": len(nodes_b),
        },
        "aggregate": {
            "duration_delta_ms": total_dur_b - total_dur_a,
            "duration_delta_pct": _pct_change(total_dur_a, total_dur_b),
            "cost_delta": round(total_cost_b - total_cost_a, 6),
            "cost_delta_pct": _pct_change(total_cost_a, total_cost_b),
            "nodes_added": len(added_nodes),
            "nodes_removed": len(removed_nodes),
            "nodes_modified": modified,
            "nodes_unchanged": unchanged,
        },
        "node_diffs": node_diffs,
    }
