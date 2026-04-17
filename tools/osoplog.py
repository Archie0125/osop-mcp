"""Generate .osoplog.yaml execution records from workflow execution results."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import yaml


def generate_osoplog(
    workflow_data: dict[str, Any],
    execution_result: dict[str, Any],
    trigger_actor: str = "user",
    agent: str = "osop-cli",
    model: str = "",
) -> str:
    """Generate an .osoplog.yaml string from execution results.

    Args:
        workflow_data: The parsed .osop workflow dict
        execution_result: The result dict from execute()
        trigger_actor: Who triggered the execution
        agent: Runtime agent name
        model: Model name if applicable

    Returns:
        YAML string of the osoplog
    """
    now = datetime.now(timezone.utc)
    duration_ms = execution_result.get("duration_ms", 0)
    from datetime import timedelta
    started_at = now - timedelta(milliseconds=duration_ms)

    node_records = []
    total_cost = 0.0

    for nr in execution_result.get("node_results", []):
        record: dict[str, Any] = {
            "node_id": nr["node_id"],
            "node_type": nr.get("type", "unknown"),
            "attempt": 1,
            "status": nr.get("status", "unknown").upper(),
            "duration_ms": nr.get("duration_ms", 0),
        }

        # Inputs
        if nr.get("resolved_inputs"):
            record["inputs"] = nr["resolved_inputs"]

        # Outputs
        if nr.get("stdout"):
            record["outputs"] = {"stdout": nr["stdout"][:500]}
        elif nr.get("content_preview"):
            record["outputs"] = {"content": nr["content_preview"][:500]}
        elif nr.get("body_preview"):
            record["outputs"] = {"body": nr["body_preview"][:500]}

        # AI metadata
        if nr.get("usage"):
            record["ai_metadata"] = {
                "model": nr.get("model", ""),
                "provider": nr.get("type", ""),
                "prompt_tokens": nr["usage"].get("input_tokens", 0),
                "completion_tokens": nr["usage"].get("output_tokens", 0),
            }

        # Tools used
        if nr.get("type") == "cli" and nr.get("status") == "completed":
            record["tools_used"] = [{"tool": "subprocess", "calls": 1}]
        elif nr.get("type") == "api" and nr.get("status") == "completed":
            record["tools_used"] = [{"tool": "httpx", "calls": 1}]
        elif nr.get("type") == "agent" and nr.get("status") == "completed":
            record["tools_used"] = [{"tool": "llm_client", "calls": 1}]

        # Cost
        if nr.get("cost_usd"):
            total_cost += nr["cost_usd"]

        # Error info
        if nr.get("error"):
            record["error"] = nr["error"][:500]
        if nr.get("reason"):
            record["reason"] = nr["reason"]

        node_records.append(record)

    log = {
        "osoplog_version": "1.0",
        "run_id": str(uuid.uuid4())[:8],
        "workflow_id": workflow_data.get("id", "unknown"),
        "mode": execution_result.get("mode", "live"),
        "status": execution_result.get("status", "unknown").upper(),
        "trigger": {
            "type": "manual",
            "actor": trigger_actor,
            "timestamp": started_at.isoformat(),
        },
        "started_at": started_at.isoformat(),
        "ended_at": now.isoformat(),
        "duration_ms": duration_ms,
        "runtime": {
            "agent": agent,
            "model": model or "multi",
            "source": "executor",
        },
        "node_records": node_records,
        "result_summary": (
            f"{execution_result.get('executed', 0)} executed, "
            f"{execution_result.get('skipped', 0)} skipped, "
            f"{execution_result.get('failed', 0)} failed"
        ),
    }

    if total_cost > 0:
        log["cost"] = {
            "total_usd": round(total_cost, 6),
            "breakdown": [
                {"node_id": nr["node_id"], "cost_usd": nr.get("cost_usd", 0)}
                for nr in execution_result.get("node_results", [])
                if nr.get("cost_usd", 0) > 0
            ],
        }

    return yaml.dump(log, default_flow_style=False, allow_unicode=True, sort_keys=False)
