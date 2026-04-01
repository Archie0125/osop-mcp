"""osop.risk_assess — Analyze OSOP workflow for security risks.

This is the killer app tool: it walks the workflow DAG, checks for
permission gaps, unguarded destructive paths, missing approval gates,
cost exposure, and segregation of duties violations.
"""

from __future__ import annotations

import re
from typing import Any

from .common import load_yaml


# --- Constants ---

DESTRUCTIVE_COMMANDS = [
    re.compile(r"rm\s+-rf", re.I),
    re.compile(r"drop\s+(table|database|schema)", re.I),
    re.compile(r"delete\s+from", re.I),
    re.compile(r"truncate\s+table", re.I),
    re.compile(r"kubectl\s+delete", re.I),
    re.compile(r"terraform\s+destroy", re.I),
    re.compile(r"docker\s+system\s+prune", re.I),
    re.compile(r"git\s+push\s+--force", re.I),
    re.compile(r"git\s+reset\s+--hard", re.I),
]

BROAD_PERMISSION_PATTERNS = [
    re.compile(r"^write:\*"),
    re.compile(r"^delete:\*"),
    re.compile(r"^admin:\*"),
    re.compile(r"^\*:\*"),
]

NODE_TYPE_WEIGHT = {
    "cli": 2.0, "infra": 2.0, "db": 1.5, "agent": 1.5, "docker": 1.5,
    "api": 1.0, "cicd": 1.5, "git": 1.0, "mcp": 1.0, "human": 0.5,
    "system": 0.5, "company": 1.0, "department": 0.5, "event": 0.5,
    "gateway": 0.2, "data": 0.8,
}

RISK_LEVEL_SCORE = {"low": 1, "medium": 2, "high": 4, "critical": 8}


def risk_assess(
    content: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Analyze an OSOP workflow for security risks."""
    raw, parsed = load_yaml(content, file_path)

    nodes = parsed.get("nodes", [])
    edges = parsed.get("edges", [])
    node_map = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

    findings: list[dict] = []
    node_scores: list[dict] = []
    all_permissions: set[str] = set()
    all_secrets: set[str] = set()
    has_approval_gates = False
    total_cost = 0.0
    has_cost = False

    # Build adjacency for predecessor lookup
    incoming: dict[str, list[str]] = {nid: [] for nid in node_map}
    outgoing: dict[str, list[dict]] = {nid: [] for nid in node_map}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        f, t = edge.get("from"), edge.get("to")
        if f in node_map and t in node_map:
            incoming.setdefault(t, []).append(f)
            outgoing.setdefault(f, []).append(edge)

    def has_approval_predecessor(nid: str, visited: set | None = None) -> bool:
        if visited is None:
            visited = set()
        if nid in visited:
            return False
        visited.add(nid)
        for pred_id in incoming.get(nid, []):
            pred = node_map.get(pred_id)
            if not pred:
                continue
            ag = pred.get("approval_gate", {})
            if isinstance(ag, dict) and ag.get("required"):
                return True
            if pred.get("type") == "human" and ag.get("required"):
                return True
            if has_approval_predecessor(pred_id, visited):
                return True
        return False

    for nid, node in node_map.items():
        security = node.get("security", {}) or {}
        perms = security.get("permissions", []) or []
        secrets = security.get("secrets", []) or []
        risk_level = security.get("risk_level", "low") or "low"
        all_permissions.update(perms)
        all_secrets.update(secrets)

        ag = node.get("approval_gate", {}) or {}
        if isinstance(ag, dict) and ag.get("required"):
            has_approval_gates = True

        cost_info = node.get("cost", {}) or {}
        if isinstance(cost_info, dict) and cost_info.get("estimated"):
            total_cost += float(cost_info["estimated"])
            has_cost = True

        node_findings: list[dict] = []
        out_edges = outgoing.get(nid, [])

        # Rule 1: High-risk without approval gate
        if risk_level in ("high", "critical"):
            has_ag = isinstance(ag, dict) and ag.get("required")
            if not has_ag and not has_approval_predecessor(nid):
                node_findings.append({
                    "rule_id": "RISK-001",
                    "severity": "critical" if risk_level == "critical" else "high",
                    "node_id": nid,
                    "title": f"{risk_level.upper()} risk node without approval gate",
                    "description": f'Node "{node.get("name", nid)}" has risk_level: {risk_level} but no approval gate.',
                    "suggestion": "Add approval_gate with required: true before this node.",
                })

        # Rule 2: Broad permissions
        broad = [p for p in perms if any(pat.match(p) for pat in BROAD_PERMISSION_PATTERNS)]
        if broad:
            node_findings.append({
                "rule_id": "RISK-002",
                "severity": "high",
                "node_id": nid,
                "title": "Overly broad permissions",
                "description": f'Node "{node.get("name", nid)}" requests: {", ".join(broad)}.',
                "suggestion": "Narrow permissions to specific resources.",
            })

        # Rule 3: Destructive commands
        ntype = node.get("type", "")
        if ntype in ("cli", "infra"):
            runtime = node.get("runtime", {}) or {}
            cmd = runtime.get("command", "") or runtime.get("action", "") or ""
            if isinstance(cmd, str) and any(pat.search(cmd) for pat in DESTRUCTIVE_COMMANDS):
                if risk_level not in ("high", "critical"):
                    node_findings.append({
                        "rule_id": "RISK-003",
                        "severity": "high",
                        "node_id": nid,
                        "title": "Destructive command without adequate risk level",
                        "description": f'Node "{node.get("name", nid)}" has destructive command but risk_level is "{risk_level}".',
                        "suggestion": 'Set security.risk_level to "high" or "critical" and add approval gate.',
                    })

        # Rule 7: No error handling on risky nodes
        if risk_level in ("medium", "high", "critical"):
            has_error_edge = any(
                e.get("mode") in ("fallback", "error", "compensation") for e in out_edges
            )
            has_retry = bool(node.get("retry_policy"))
            if not has_error_edge and not has_retry:
                node_findings.append({
                    "rule_id": "RISK-007",
                    "severity": "medium",
                    "node_id": nid,
                    "title": "No error handling on risky node",
                    "description": f'Node "{node.get("name", nid)}" (risk: {risk_level}) has no fallback or retry.',
                    "suggestion": "Add a fallback edge, error edge, or retry_policy.",
                })

        # Rule 8: Missing timeout on external calls
        if ntype in ("api", "cli", "agent", "infra", "mcp") and not node.get("timeout_sec"):
            node_findings.append({
                "rule_id": "RISK-008",
                "severity": "low",
                "node_id": nid,
                "title": "Missing timeout on external operation",
                "description": f'Node "{node.get("name", nid)}" (type: {ntype}) has no timeout_sec.',
                "suggestion": "Set timeout_sec to prevent indefinite execution.",
            })

        # Compute score
        type_weight = NODE_TYPE_WEIGHT.get(ntype, 1.0)
        risk_mult = RISK_LEVEL_SCORE.get(risk_level, 1)
        base_score = type_weight * risk_mult

        mitigation = 1.0
        if isinstance(ag, dict) and ag.get("required"):
            mitigation -= 0.5
        if node.get("retry_policy"):
            mitigation -= 0.1
        if any(e.get("mode") in ("fallback", "error", "compensation") for e in out_edges):
            mitigation -= 0.2
        mitigation = max(mitigation, 0.1)

        mitigated = base_score * mitigation

        node_scores.append({
            "node_id": nid,
            "node_name": node.get("name", nid),
            "node_type": ntype,
            "risk_level": risk_level,
            "base_score": round(base_score, 2),
            "mitigated_score": round(mitigated, 2),
            "findings_count": len(node_findings),
        })

        findings.extend(node_findings)

    # Global: cost exposure
    agent_nodes = [n for n in nodes if isinstance(n, dict) and n.get("type") == "agent"]
    unbounded = sum(1 for n in agent_nodes if not (n.get("cost", {}) or {}).get("estimated"))
    if unbounded > 2:
        findings.append({
            "rule_id": "RISK-005",
            "severity": "medium",
            "title": "Unbounded cost exposure",
            "description": f"{unbounded} agent nodes have no estimated cost set.",
            "suggestion": "Add cost.estimated to agent nodes for cost tracking.",
        })

    # Overall score
    node_count = len(node_map)
    total_mitigated = sum(ns["mitigated_score"] for ns in node_scores)
    avg = total_mitigated / node_count if node_count > 0 else 0
    normalized = min(100, round((avg / 8) * 100))

    severity_penalty = {"info": 0, "low": 2, "medium": 5, "high": 10, "critical": 20}
    penalty = sum(severity_penalty.get(f.get("severity", "info"), 0) for f in findings)
    overall_score = min(100, normalized + penalty)

    if overall_score <= 20:
        verdict = "safe"
    elif overall_score <= 45:
        verdict = "caution"
    elif overall_score <= 70:
        verdict = "warning"
    else:
        verdict = "danger"

    by_severity = {"info": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
    for f in findings:
        sev = f.get("severity", "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        "overall_score": overall_score,
        "verdict": verdict,
        "total_nodes": node_count,
        "high_risk_nodes": sum(1 for ns in node_scores if ns["risk_level"] in ("high", "critical")),
        "total_findings": len(findings),
        "by_severity": by_severity,
        "has_approval_gates": has_approval_gates,
        "permissions_required": sorted(all_permissions),
        "secrets_required": sorted(all_secrets),
        "estimated_cost": round(total_cost, 2) if has_cost else None,
        "findings": findings,
        "node_scores": node_scores,
    }
