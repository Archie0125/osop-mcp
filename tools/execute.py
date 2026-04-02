"""OSOP workflow executor — run CLI and API nodes with timeout support."""

from __future__ import annotations

import asyncio
import subprocess
import time
from typing import Any

import yaml

from .common import load_yaml


def _topo_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Topological sort of node IDs."""
    node_ids = {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}
    in_deg: dict[str, int] = {nid: 0 for nid in node_ids}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}

    for e in edges:
        if not isinstance(e, dict):
            continue
        f, t = e.get("from", ""), e.get("to", "")
        if f in adj and t in in_deg:
            adj[f].append(t)
            in_deg[t] += 1

    queue = [nid for nid, deg in in_deg.items() if deg == 0]
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for child in adj.get(nid, []):
            in_deg[child] -= 1
            if in_deg[child] == 0:
                queue.append(child)

    # Add any remaining (cycles)
    for nid in node_ids:
        if nid not in order:
            order.append(nid)
    return order


def execute(
    content: str | None = None,
    file_path: str | None = None,
    inputs: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Execute an OSOP workflow.

    Currently supports:
    - `cli` nodes: runs shell commands via subprocess
    - `api` nodes: makes HTTP requests (requires httpx)
    - Other nodes: logged as skipped (need external runtime)

    Args:
        content: OSOP YAML content
        file_path: Path to .osop.yaml file
        inputs: Input values for the workflow
        dry_run: If True, simulate without executing
        timeout_seconds: Maximum total execution time
    """
    _, data = load_yaml(content=content, file_path=file_path)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}
    order = _topo_sort(nodes, edges)

    start_time = time.time()
    results: list[dict[str, Any]] = []
    status = "completed"

    for nid in order:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            results.append({"node_id": nid, "status": "skipped", "reason": "timeout exceeded"})
            status = "timeout"
            continue

        node = node_map.get(nid)
        if not node:
            continue

        node_type = node.get("type", "system")
        node_timeout = node.get("timeout_sec", timeout_seconds - elapsed)
        node_result: dict[str, Any] = {
            "node_id": nid,
            "type": node_type,
            "name": node.get("name", nid),
        }

        if dry_run:
            node_result["status"] = "dry_run"
            node_result["message"] = f"Would execute {node_type} node: {node.get('name', nid)}"
            results.append(node_result)
            continue

        node_start = time.time()
        try:
            if node_type == "cli":
                runtime = node.get("runtime", {})
                command = None
                if isinstance(runtime, dict):
                    command = runtime.get("command") or runtime.get("config", {}).get("command")
                if not command:
                    # Look in description for a command hint
                    node_result["status"] = "skipped"
                    node_result["reason"] = "No command specified in runtime.command"
                else:
                    proc = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=min(node_timeout, timeout_seconds - elapsed),
                    )
                    node_result["status"] = "completed" if proc.returncode == 0 else "failed"
                    node_result["exit_code"] = proc.returncode
                    node_result["stdout"] = proc.stdout[:2000] if proc.stdout else ""
                    node_result["stderr"] = proc.stderr[:2000] if proc.stderr else ""
                    if proc.returncode != 0:
                        status = "failed"

            elif node_type == "api":
                runtime = node.get("runtime", {})
                endpoint = runtime.get("endpoint", "") if isinstance(runtime, dict) else ""
                method = (runtime.get("method", "GET") if isinstance(runtime, dict) else "GET").upper()
                url = runtime.get("url", "") if isinstance(runtime, dict) else ""

                if not url and not endpoint:
                    node_result["status"] = "skipped"
                    node_result["reason"] = "No URL/endpoint specified in runtime"
                else:
                    try:
                        import httpx
                        full_url = url + endpoint if url else endpoint
                        with httpx.Client(timeout=min(node_timeout, 30)) as client:
                            resp = client.request(method, full_url)
                            node_result["status"] = "completed" if resp.status_code < 400 else "failed"
                            node_result["status_code"] = resp.status_code
                            node_result["body_preview"] = resp.text[:500]
                    except ImportError:
                        node_result["status"] = "skipped"
                        node_result["reason"] = "httpx not installed — cannot execute API nodes"
                    except Exception as e:
                        node_result["status"] = "failed"
                        node_result["error"] = str(e)
                        status = "failed"

            elif node_type in ("human", "agent"):
                node_result["status"] = "skipped"
                node_result["reason"] = f"{node_type} nodes require external runtime (LLM/human interaction)"

            else:
                node_result["status"] = "skipped"
                node_result["reason"] = f"No built-in executor for type: {node_type}"

        except subprocess.TimeoutExpired:
            node_result["status"] = "timeout"
            status = "timeout"
        except Exception as e:
            node_result["status"] = "error"
            node_result["error"] = str(e)
            status = "failed"

        node_result["duration_ms"] = int((time.time() - node_start) * 1000)
        results.append(node_result)

    total_duration = int((time.time() - start_time) * 1000)
    executed = sum(1 for r in results if r.get("status") == "completed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    failed = sum(1 for r in results if r.get("status") in ("failed", "error", "timeout"))

    return {
        "status": status,
        "mode": "dry_run" if dry_run else "live",
        "workflow": data.get("name", data.get("id", "")),
        "total_nodes": len(order),
        "executed": executed,
        "skipped": skipped,
        "failed": failed,
        "duration_ms": total_duration,
        "node_results": results,
    }
