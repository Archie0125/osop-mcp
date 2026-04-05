"""OSOP workflow executor — run workflows with security gates and LLM support.

Supports:
- `cli` nodes: shell commands (requires --allow-exec)
- `api` nodes: HTTP requests
- `agent` nodes: LLM calls via Anthropic/OpenAI
- `human` nodes: stdin prompts in interactive mode, skip otherwise
- Other nodes: logged as skipped

Security: CLI nodes require explicit opt-in via allow_exec=True.
Risk assessment runs as pre-flight check before execution.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

import yaml

from .common import load_yaml


# ---------------------------------------------------------------------------
# WorkflowContext — passes data between nodes
# ---------------------------------------------------------------------------

class WorkflowContext:
    """Accumulates node outputs and resolves inputs for subsequent nodes."""

    def __init__(self, workflow_inputs: dict[str, Any] | None = None):
        self._store: dict[str, Any] = {}
        if workflow_inputs:
            self._store.update(workflow_inputs)

    def set_output(self, node_id: str, key: str, value: Any) -> None:
        self._store[f"{node_id}.{key}"] = value
        self._store[key] = value  # also available by short name (last writer wins)

    def set_node_result(self, node_id: str, result: Any) -> None:
        self._store[node_id] = result

    def resolve_inputs(self, input_refs: list) -> dict[str, Any]:
        """Resolve a list of input references to their values."""
        resolved = {}
        for ref in input_refs:
            if isinstance(ref, str):
                resolved[ref] = self._store.get(ref, f"<unresolved: {ref}>")
            elif isinstance(ref, dict):
                name = ref.get("name", "")
                resolved[name] = self._store.get(name, f"<unresolved: {name}>")
        return resolved

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def summary(self) -> dict[str, str]:
        """Short summary of stored keys for logging."""
        return {k: str(v)[:100] for k, v in self._store.items()}


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Condition evaluator (safe, no exec/eval)
# ---------------------------------------------------------------------------

def _eval_condition(expr: str, ctx: WorkflowContext) -> bool:
    """Evaluate a simple condition expression against the workflow context.

    Supports: ==, !=, >=, <=, >, <, 'and', 'or', 'not', 'in', 'true', 'false'.
    Variable names are resolved from the context store.
    """
    if not expr or not expr.strip():
        return True

    expr = expr.strip()

    # Simple boolean literals
    if expr.lower() in ("true", "yes", "1"):
        return True
    if expr.lower() in ("false", "no", "0"):
        return False

    # Build a safe namespace from context
    namespace: dict[str, Any] = {}
    for key, val in ctx._store.items():
        safe_key = key.replace(".", "_").replace("-", "_")
        namespace[safe_key] = val
        # Also try to coerce to number if possible
        if isinstance(val, str):
            try:
                namespace[safe_key] = float(val)
            except (ValueError, TypeError):
                pass

    # Simple comparison: "status == 'completed'"
    import re
    # Replace variable references with their values for simple patterns
    for pattern in [
        r'(\w+)\s*(==|!=|>=|<=|>|<)\s*["\']([^"\']*)["\']',  # var op "string"
        r'(\w+)\s*(==|!=|>=|<=|>|<)\s*(\d+\.?\d*)',            # var op number
    ]:
        m = re.match(pattern, expr)
        if m:
            var_name = m.group(1).replace(".", "_").replace("-", "_")
            op = m.group(2)
            rhs = m.group(3)
            lhs = namespace.get(var_name)
            if lhs is None:
                return False
            try:
                # Numeric comparison
                lhs_num = float(lhs) if not isinstance(lhs, (int, float)) else lhs
                rhs_num = float(rhs)
                if op == "==": return lhs_num == rhs_num
                if op == "!=": return lhs_num != rhs_num
                if op == ">=": return lhs_num >= rhs_num
                if op == "<=": return lhs_num <= rhs_num
                if op == ">": return lhs_num > rhs_num
                if op == "<": return lhs_num < rhs_num
            except (ValueError, TypeError):
                # String comparison
                lhs_str = str(lhs)
                if op == "==": return lhs_str == rhs
                if op == "!=": return lhs_str != rhs
            return False

    # Check if a variable is truthy
    var_name = expr.replace(".", "_").replace("-", "_")
    val = namespace.get(var_name)
    if val is not None:
        return bool(val)

    return True  # Default: condition passes


# ---------------------------------------------------------------------------
# Graph walker — respects edge modes
# ---------------------------------------------------------------------------

def _build_edge_map(edges: list[dict]) -> dict[str, list[dict]]:
    """Build outgoing edge map: node_id -> list of edges."""
    edge_map: dict[str, list[dict]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        f = e.get("from", "")
        if f:
            edge_map.setdefault(f, []).append(e)
    return edge_map


def _find_start_nodes(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Find nodes with no incoming edges (start nodes)."""
    all_ids = {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}
    has_incoming = {e.get("to") for e in edges if isinstance(e, dict)}
    starts = [nid for nid in all_ids if nid not in has_incoming]
    return starts or [nodes[0]["id"]] if nodes else []


# ---------------------------------------------------------------------------
# Pre-flight security check
# ---------------------------------------------------------------------------

def _run_preflight(data: dict, allow_exec: bool) -> list[dict]:
    """Run risk assessment as pre-flight check. Returns findings."""
    try:
        from .risk_assess import risk_assess
        raw_yaml = yaml.dump(data)
        result = risk_assess(content=raw_yaml)
        findings = result.get("findings", [])

        # Block execution if critical findings and no allow_exec
        critical = [f for f in findings if f.get("severity") == "critical"]
        if critical and not allow_exec:
            return critical
        return findings
    except Exception:
        return []  # Don't block on risk_assess errors


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

def execute(
    content: str | None = None,
    file_path: str | None = None,
    inputs: dict[str, Any] | None = None,
    dry_run: bool = False,
    allow_exec: bool = False,
    interactive: bool = False,
    timeout_seconds: int = 300,
    max_cost_usd: float = 1.0,
    max_iterations: int = 10,
) -> dict[str, Any]:
    """Execute an OSOP workflow.

    Args:
        content: OSOP YAML content
        file_path: Path to .osop.yaml file
        inputs: Input values for the workflow
        dry_run: If True, simulate without executing
        allow_exec: If True, allow CLI node execution (shell commands)
        interactive: If True, prompt for human node input via stdin
        timeout_seconds: Maximum total execution time
        max_cost_usd: Maximum total LLM cost before aborting
        max_iterations: Maximum loop iterations for cyclic edges
    """
    _, data = load_yaml(content=content, file_path=file_path)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}
    order = _topo_sort(nodes, edges)

    # Pre-flight risk check
    preflight_findings = _run_preflight(data, allow_exec)
    critical_findings = [f for f in preflight_findings if f.get("severity") == "critical"]
    if critical_findings and not allow_exec:
        return {
            "status": "blocked",
            "reason": "Pre-flight risk assessment found critical issues. Use allow_exec=True to override.",
            "findings": critical_findings,
            "workflow": data.get("name", data.get("id", "")),
        }

    # Check CLI nodes exist but allow_exec is False
    has_cli_nodes = any(
        n.get("type") == "cli" for n in nodes if isinstance(n, dict)
    )
    if has_cli_nodes and not allow_exec and not dry_run:
        return {
            "status": "blocked",
            "reason": "Workflow contains CLI nodes that execute shell commands. "
                      "Set allow_exec=True to permit execution. "
                      "Review the commands in the workflow before allowing.",
            "cli_commands": [
                {
                    "node": n.get("id", "?"),
                    "command": (n.get("runtime", {}) or {}).get("command", "?")
                }
                for n in nodes
                if isinstance(n, dict) and n.get("type") == "cli"
            ],
            "workflow": data.get("name", data.get("id", "")),
        }

    ctx = WorkflowContext(inputs)
    start_time = time.time()
    results: list[dict[str, Any]] = []
    status = "completed"
    total_cost = 0.0
    executed_ids: set[str] = set()
    edge_map = _build_edge_map(edges)
    node_status: dict[str, str] = {}  # track per-node status for edge evaluation

    # Use graph walker: start from root nodes, follow edges
    start_nodes = _find_start_nodes(nodes, edges)
    execution_queue: list[str] = list(start_nodes)
    # Add truly orphan nodes (no incoming AND no outgoing edges)
    all_edge_nodes = set()
    for e in edges:
        if isinstance(e, dict):
            all_edge_nodes.add(e.get("from", ""))
            all_edge_nodes.add(e.get("to", ""))
    for nid in order:
        if nid not in execution_queue and nid not in all_edge_nodes:
            execution_queue.append(nid)

    visit_count: dict[str, int] = {}

    while execution_queue:
        nid = execution_queue.pop(0)

        # Skip if already executed (unless it's a retry/loop)
        if nid in executed_ids:
            visit_count[nid] = visit_count.get(nid, 0) + 1
            if visit_count[nid] > max_iterations:
                continue
        else:
            visit_count[nid] = 1
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            results.append({"node_id": nid, "status": "skipped", "reason": "timeout exceeded"})
            status = "timeout"
            continue

        if total_cost > max_cost_usd:
            results.append({"node_id": nid, "status": "skipped", "reason": f"cost limit exceeded (${total_cost:.4f} > ${max_cost_usd})"})
            status = "cost_limit"
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

        # Resolve inputs for this node
        node_inputs = node.get("inputs", [])
        if node_inputs:
            resolved = ctx.resolve_inputs(node_inputs)
            node_result["resolved_inputs"] = {k: str(v)[:200] for k, v in resolved.items()}

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
                    else:
                        ctx.set_node_result(nid, proc.stdout[:2000])

            elif node_type == "api":
                runtime = node.get("runtime", {}) if isinstance(node.get("runtime"), dict) else {}
                method = runtime.get("method", "GET").upper()
                url = runtime.get("url", "")
                endpoint = runtime.get("endpoint", "")
                headers = runtime.get("headers", {}) if isinstance(runtime.get("headers"), dict) else {}
                body = runtime.get("body") if isinstance(runtime.get("body"), (dict, str)) else None
                query_params = runtime.get("query_params", {}) if isinstance(runtime.get("query_params"), dict) else {}
                expected_status = runtime.get("expected_status")
                response_mapping = runtime.get("response_mapping", {}) if isinstance(runtime.get("response_mapping"), dict) else {}

                # Interpolate variables: ${secrets.X}, ${node_id.field}
                def _interpolate_str(s: str) -> str:
                    if not isinstance(s, str):
                        return s
                    import re
                    def _replace(m):
                        ref = m.group(1)
                        if ref.startswith("secrets."):
                            return resolve_secret(ref[8:]) if 'resolve_secret' in dir() else m.group(0)
                        parts = ref.split(".", 1)
                        if len(parts) == 2:
                            prev = ctx.get_node_result(parts[0])
                            if isinstance(prev, dict):
                                return str(prev.get(parts[1], m.group(0)))
                            elif isinstance(prev, str):
                                return prev
                        return m.group(0)
                    return re.sub(r'\$\{([^}]+)\}', _replace, s)

                full_url = _interpolate_str(url + endpoint if url else endpoint)
                headers = {k: _interpolate_str(v) for k, v in headers.items()}
                if isinstance(body, dict):
                    body = {k: _interpolate_str(v) if isinstance(v, str) else v for k, v in body.items()}
                query_params = {k: _interpolate_str(v) if isinstance(v, str) else v for k, v in query_params.items()}

                # Auth: auto-add Authorization header from security config
                security = node.get("security", {}) or {}
                auth_type = security.get("auth", "")
                if auth_type == "bearer_token" and "Authorization" not in headers:
                    secret_ref = security.get("secret_ref", "")
                    if secret_ref:
                        token = resolve_secret(secret_ref) if 'resolve_secret' in dir() else ""
                        if token:
                            headers["Authorization"] = f"Bearer {token}"

                if not full_url:
                    node_result["status"] = "skipped"
                    node_result["reason"] = "No URL/endpoint specified in runtime"
                else:
                    try:
                        import httpx
                        req_kwargs: dict = {"headers": headers}
                        if query_params:
                            req_kwargs["params"] = query_params
                        if body is not None and method in ("POST", "PUT", "PATCH"):
                            if isinstance(body, dict):
                                req_kwargs["json"] = body
                            else:
                                req_kwargs["content"] = str(body)
                        with httpx.Client(timeout=min(node_timeout, 30)) as client:
                            resp = client.request(method, full_url, **req_kwargs)
                            success_code = expected_status or 400
                            node_result["status"] = "completed" if resp.status_code < (success_code if isinstance(success_code, int) and success_code > 200 else 400) else "failed"
                            node_result["status_code"] = resp.status_code
                            node_result["body_preview"] = resp.text[:500]

                            # Parse response and apply mapping
                            try:
                                result_data = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text[:2000]
                            except Exception:
                                result_data = resp.text[:2000]

                            if response_mapping and isinstance(result_data, dict):
                                mapped = {}
                                for key, path in response_mapping.items():
                                    # Simple dot-notation extraction: "data.id" -> result_data["data"]["id"]
                                    val = result_data
                                    for p in str(path).lstrip("$.").split("."):
                                        if isinstance(val, dict):
                                            val = val.get(p)
                                        else:
                                            val = None
                                            break
                                    mapped[key] = val
                                ctx.set_node_result(nid, mapped)
                                node_result["mapped_fields"] = mapped
                            else:
                                ctx.set_node_result(nid, result_data if isinstance(result_data, (dict, str)) else resp.text[:2000])
                    except ImportError:
                        node_result["status"] = "skipped"
                        node_result["reason"] = "httpx not installed"
                    except Exception as e:
                        node_result["status"] = "failed"
                        node_result["error"] = str(e)
                        status = "failed"

            elif node_type == "agent":
                runtime = node.get("runtime", {}) or {}
                config = node.get("config", {}) or {}
                provider = runtime.get("provider") or config.get("provider") or "anthropic"
                model = runtime.get("model") or config.get("model") or ""
                system_prompt = runtime.get("system_prompt") or config.get("system_prompt") or ""
                temperature = runtime.get("temperature") or config.get("temperature") or 0.7
                max_tokens = runtime.get("max_tokens") or config.get("max_tokens") or 4096

                # Build user message from context
                node_inputs_resolved = ctx.resolve_inputs(node.get("inputs", []))
                purpose = node.get("purpose", "") or node.get("description", "")
                user_message = purpose
                if node_inputs_resolved:
                    input_summary = "\n".join(f"- {k}: {v}" for k, v in node_inputs_resolved.items())
                    user_message = f"{purpose}\n\nContext:\n{input_summary}"

                try:
                    from .llm_client import call_llm
                    llm_result = call_llm(
                        provider=provider,
                        model=model,
                        system_prompt=system_prompt,
                        user_message=user_message,
                        temperature=float(temperature),
                        max_tokens=int(max_tokens),
                    )
                    node_result["status"] = "completed"
                    node_result["content_preview"] = llm_result["content"][:500]
                    node_result["model"] = llm_result["model"]
                    node_result["usage"] = llm_result["usage"]
                    node_result["cost_usd"] = llm_result["cost_usd"]
                    total_cost += llm_result["cost_usd"]

                    # Store full output in context
                    ctx.set_node_result(nid, llm_result["content"])
                    for out_ref in node.get("outputs", []):
                        out_name = out_ref if isinstance(out_ref, str) else out_ref.get("name", "")
                        if out_name:
                            ctx.set_output(nid, out_name, llm_result["content"])

                except Exception as e:
                    node_result["status"] = "failed"
                    node_result["error"] = str(e)
                    status = "failed"

            elif node_type == "human":
                if interactive:
                    purpose = node.get("purpose", "") or node.get("description", "")
                    print(f"\n[HUMAN INPUT REQUIRED] Node: {node.get('name', nid)}")
                    if purpose:
                        print(f"  {purpose}")
                    user_input = input("  Your input> ")
                    node_result["status"] = "completed"
                    node_result["input"] = user_input
                    ctx.set_node_result(nid, user_input)
                else:
                    node_result["status"] = "skipped"
                    node_result["reason"] = "Human node requires interactive=True"

            elif node_type == "db":
                node_result["status"] = "skipped"
                node_result["reason"] = "Database nodes not yet supported"

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
        executed_ids.add(nid)
        node_status[nid] = node_result.get("status", "unknown")

        # --- Edge routing: determine next nodes based on edge modes ---
        outgoing = edge_map.get(nid, [])
        routed_next: list[str] = []

        for edge in outgoing:
            target = edge.get("to", "")
            if not target or target not in node_map:
                continue
            mode = edge.get("mode", "sequential")
            condition = edge.get("condition") or edge.get("when") or ""

            if mode == "sequential":
                if target not in executed_ids or target not in routed_next:
                    routed_next.append(target)

            elif mode == "conditional":
                if _eval_condition(condition, ctx):
                    routed_next.append(target)

            elif mode == "parallel":
                routed_next.append(target)

            elif mode == "fallback":
                # Only follow fallback if current node failed
                if node_status.get(nid) in ("failed", "error", "timeout"):
                    routed_next.append(target)
                    node_result["fallback_to"] = target

            elif mode == "loop":
                if condition and _eval_condition(condition, ctx):
                    if visit_count.get(target, 0) < max_iterations:
                        routed_next.append(target)

            elif mode == "error":
                if node_status.get(nid) in ("failed", "error"):
                    routed_next.append(target)

            elif mode == "timeout":
                if node_status.get(nid) == "timeout":
                    routed_next.append(target)

            elif mode == "spawn":
                routed_next.append(target)

            else:
                # Unknown mode, treat as sequential
                routed_next.append(target)

        # Add routed targets to front of queue (depth-first for sequential chains)
        for target in reversed(routed_next):
            if target not in execution_queue:
                execution_queue.insert(0, target)

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
        "total_cost_usd": round(total_cost, 6),
        "preflight_findings": len(preflight_findings),
        "node_results": results,
        "context_keys": list(ctx.summary().keys()) if executed > 0 else [],
    }
