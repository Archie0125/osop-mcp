"""osop.optimize — Analyze workflow and suggest data-driven optimizations.

Consumes optional run_history to identify slow steps, failure hotspots,
bottlenecks, and parallelization opportunities. Can produce modified YAML.
"""

from __future__ import annotations

import json
import copy
from typing import Any

import yaml

from .common import load_yaml


def optimize(
    content: str | None = None,
    file_path: str | None = None,
    apply: bool = False,
    run_history: str | None = None,
) -> dict[str, Any]:
    """Analyze an OSOP workflow and suggest optimizations."""
    raw, parsed = load_yaml(content, file_path)

    nodes = parsed.get("nodes", [])
    edges = parsed.get("edges", [])
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    # Parse run history if provided
    history: list[dict] = []
    if run_history:
        try:
            history = json.loads(run_history)
        except (json.JSONDecodeError, TypeError):
            pass

    suggestions: list[dict] = []
    node_stats: dict[str, dict] = {}

    # --- Aggregate stats from run history ---
    if history:
        for run in history:
            for nr in run.get("node_records", []):
                nid = nr.get("node_id", "")
                if nid not in node_stats:
                    node_stats[nid] = {"durations": [], "failures": 0, "total": 0, "errors": []}
                ns = node_stats[nid]
                ns["total"] += 1
                if nr.get("duration_ms"):
                    ns["durations"].append(nr["duration_ms"])
                if nr.get("status") == "FAILED":
                    ns["failures"] += 1
                    err = nr.get("error", {}).get("message", "")
                    if err and err not in ns["errors"]:
                        ns["errors"].append(err)

    # --- Analysis ---

    slow_steps = []
    failure_hotspots = []
    bottlenecks = []

    for nid, ns in node_stats.items():
        avg_dur = sum(ns["durations"]) / len(ns["durations"]) if ns["durations"] else 0
        fail_rate = ns["failures"] / ns["total"] if ns["total"] > 0 else 0

        if avg_dur > 5000:  # > 5s is slow
            slow_steps.append({"node_id": nid, "avg_duration_ms": round(avg_dur)})
        if fail_rate > 0.1:  # > 10% failure rate
            failure_hotspots.append({"node_id": nid, "failure_rate": round(fail_rate, 3), "common_errors": ns["errors"][:3]})
        if avg_dur > 5000 and fail_rate > 0.1:
            bottlenecks.append({"node_id": nid, "reason": f"slow ({round(avg_dur)}ms avg) AND unreliable ({round(fail_rate*100)}% failure)"})

    # --- Static analysis (no history needed) ---

    # Check for missing retry on external calls
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        nid = node.get("id", "")

        if ntype in ("api", "cli", "agent", "infra", "mcp") and not node.get("retry_policy"):
            # Check if it's a failure hotspot
            is_hotspot = any(h["node_id"] == nid for h in failure_hotspots)
            suggestions.append({
                "type": "add_retry",
                "target_node_ids": [nid],
                "description": f'Node "{node.get("name", nid)}" ({ntype}) has no retry policy.' +
                    (f' It fails {round(node_stats.get(nid, {}).get("failures", 0) / max(node_stats.get(nid, {}).get("total", 1), 1) * 100)}% of the time.' if is_hotspot else ''),
                "priority": "high" if is_hotspot else "medium",
            })

    # Check for missing timeout on external calls
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        if ntype in ("api", "cli", "agent", "infra", "mcp") and not node.get("timeout_sec"):
            nid = node.get("id", "")
            avg = 0
            if nid in node_stats and node_stats[nid]["durations"]:
                p95 = sorted(node_stats[nid]["durations"])[int(len(node_stats[nid]["durations"]) * 0.95)]
                avg = p95
            suggestions.append({
                "type": "optimize",
                "target_node_ids": [nid],
                "description": f'Node "{node.get("name", nid)}" has no timeout.' +
                    (f' Based on history, recommend timeout_sec: {max(round(avg / 1000 * 2), 30)}.' if avg > 0 else ''),
                "priority": "low",
            })

    # Check for parallelization opportunities
    sequential_chains = _find_sequential_chains(nodes, edges)
    for chain in sequential_chains:
        if len(chain) >= 3:
            # Check if nodes in the chain are independent (no data dependencies)
            independent = _check_independence(chain, node_map)
            if independent:
                suggestions.append({
                    "type": "parallelize",
                    "target_node_ids": chain,
                    "description": f'Sequential chain of {len(chain)} independent nodes could be parallelized: {" -> ".join(chain)}.',
                    "priority": "medium",
                })

    # Check for missing fallback on critical paths
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "")
        risk = (node.get("security") or {}).get("risk_level", "low")
        if risk in ("high", "critical"):
            out_edges = [e for e in edges if isinstance(e, dict) and e.get("from") == nid]
            has_fallback = any(e.get("mode") in ("fallback", "error", "compensation") for e in out_edges)
            if not has_fallback:
                suggestions.append({
                    "type": "restructure",
                    "target_node_ids": [nid],
                    "description": f'High-risk node "{node.get("name", nid)}" has no fallback edge. Consider adding error handling.',
                    "priority": "high",
                })

    # --- Generate modified YAML if apply=true ---
    proposed_yaml = None
    if apply and suggestions:
        proposed = copy.deepcopy(parsed)
        proposed_nodes = {n["id"]: n for n in proposed.get("nodes", []) if isinstance(n, dict)}

        for s in suggestions:
            if s["type"] == "add_retry":
                for tid in s["target_node_ids"]:
                    if tid in proposed_nodes and not proposed_nodes[tid].get("retry_policy"):
                        proposed_nodes[tid]["retry_policy"] = {
                            "max_retries": 3,
                            "strategy": "exponential_backoff",
                            "backoff_sec": 5,
                        }

            elif s["type"] == "optimize" and "timeout" in s["description"].lower():
                for tid in s["target_node_ids"]:
                    if tid in proposed_nodes and not proposed_nodes[tid].get("timeout_sec"):
                        proposed_nodes[tid]["timeout_sec"] = 120

        # Update version
        meta = proposed.get("metadata", {})
        if isinstance(meta, dict):
            old_v = meta.get("version", "0.0.0")
            parts = old_v.split(".")
            if len(parts) == 3:
                parts[2] = str(int(parts[2]) + 1)
                meta["version"] = ".".join(parts)
            proposed["metadata"] = meta

        proposed_yaml = yaml.dump(proposed, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return {
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "analysis": {
            "slow_steps": slow_steps,
            "failure_hotspots": failure_hotspots,
            "bottlenecks": bottlenecks,
        },
        "proposed_yaml": proposed_yaml,
    }


def _find_sequential_chains(nodes: list, edges: list) -> list[list[str]]:
    """Find chains of sequential edges."""
    seq_edges = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        if e.get("mode", "sequential") == "sequential":
            seq_edges[e["from"]] = e["to"]

    chains = []
    visited = set()
    for nid in [n.get("id") for n in nodes if isinstance(n, dict)]:
        if nid in visited or nid not in seq_edges:
            continue
        chain = [nid]
        current = nid
        while current in seq_edges:
            nxt = seq_edges[current]
            chain.append(nxt)
            visited.add(nxt)
            current = nxt
        if len(chain) >= 3:
            chains.append(chain)

    return chains


def _check_independence(chain: list[str], node_map: dict) -> bool:
    """Check if nodes in a chain are data-independent (can be parallelized)."""
    output_names = set()
    for nid in chain:
        node = node_map.get(nid)
        if not node:
            continue
        inputs = node.get("inputs", []) or []
        for inp in inputs:
            if isinstance(inp, dict) and inp.get("name") in output_names:
                return False  # This node depends on a prior node's output
        outputs = node.get("outputs", []) or []
        for out in outputs:
            if isinstance(out, dict):
                output_names.add(out.get("name"))
    return True
