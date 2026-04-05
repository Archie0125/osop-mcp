"""osop.synthesize — Feed multiple .osoplog execution records to an LLM,
get back an optimized .osop workflow definition.

The killer feature: you work, generating logs. The AI reads the patterns
and produces a better workflow. You focus on doing, not on process design.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from .common import load_yaml


def _load_logs(log_paths: list[str]) -> list[dict]:
    """Load multiple .osoplog.yaml files."""
    logs = []
    for p in log_paths:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                logs.append(data)
        except Exception:
            continue
    return logs


def _aggregate_stats(logs: list[dict]) -> dict[str, Any]:
    """Aggregate statistics across multiple execution logs."""
    all_nodes: dict[str, dict] = {}
    total_runs = len(logs)
    total_duration = 0
    total_cost = 0.0
    statuses: dict[str, int] = {}

    for log in logs:
        total_duration += log.get("duration_ms", 0)
        cost = log.get("cost", {})
        if isinstance(cost, dict):
            total_cost += cost.get("total_usd", 0)

        run_status = log.get("status", "UNKNOWN")
        statuses[run_status] = statuses.get(run_status, 0) + 1

        for nr in log.get("node_records", []):
            nid = nr.get("node_id", "")
            if not nid:
                continue
            if nid not in all_nodes:
                all_nodes[nid] = {
                    "node_type": nr.get("node_type", "unknown"),
                    "durations": [],
                    "costs": [],
                    "statuses": [],
                    "errors": [],
                    "outputs_samples": [],
                }
            stats = all_nodes[nid]
            if nr.get("duration_ms"):
                stats["durations"].append(nr["duration_ms"])
            if nr.get("cost_usd"):
                stats["costs"].append(nr["cost_usd"])
            stats["statuses"].append(nr.get("status", "UNKNOWN"))
            if nr.get("error"):
                stats["errors"].append(str(nr["error"])[:200])
            if nr.get("outputs"):
                out = nr["outputs"]
                if isinstance(out, dict):
                    sample = {k: str(v)[:100] for k, v in list(out.items())[:3]}
                    stats["outputs_samples"].append(sample)

    # Compute per-node summaries
    node_summaries = {}
    for nid, stats in all_nodes.items():
        durs = stats["durations"]
        costs = stats["costs"]
        status_counts = {}
        for s in stats["statuses"]:
            status_counts[s] = status_counts.get(s, 0) + 1

        node_summaries[nid] = {
            "node_type": stats["node_type"],
            "runs": len(stats["statuses"]),
            "avg_duration_ms": round(sum(durs) / len(durs)) if durs else 0,
            "max_duration_ms": max(durs) if durs else 0,
            "min_duration_ms": min(durs) if durs else 0,
            "total_cost_usd": round(sum(costs), 6),
            "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else 0,
            "success_rate": round(status_counts.get("COMPLETED", 0) / len(stats["statuses"]), 3) if stats["statuses"] else 0,
            "failure_rate": round(
                (status_counts.get("FAILED", 0) + status_counts.get("ERROR", 0)) / len(stats["statuses"]), 3
            ) if stats["statuses"] else 0,
            "common_errors": list(set(stats["errors"]))[:3],
            "status_breakdown": status_counts,
        }

    return {
        "total_runs": total_runs,
        "total_duration_ms": total_duration,
        "total_cost_usd": round(total_cost, 6),
        "avg_duration_ms": round(total_duration / total_runs) if total_runs else 0,
        "run_statuses": statuses,
        "node_summaries": node_summaries,
    }


def _build_synthesis_prompt(
    logs: list[dict],
    stats: dict[str, Any],
    base_osop: dict | None = None,
    goal: str = "",
) -> str:
    """Build the LLM prompt for workflow synthesis."""

    base_section = ""
    if base_osop:
        base_yaml = yaml.dump(base_osop, default_flow_style=False, allow_unicode=True, sort_keys=False)
        base_section = f"""
## Current Workflow Definition (.osop)

```yaml
{base_yaml}
```
"""

    node_analysis = ""
    for nid, ns in stats.get("node_summaries", {}).items():
        node_analysis += f"""
### Node: {nid} (type: {ns['node_type']})
- Runs: {ns['runs']} | Success rate: {ns['success_rate']*100:.0f}%
- Avg duration: {ns['avg_duration_ms']}ms | Max: {ns['max_duration_ms']}ms
- Avg cost: ${ns['avg_cost_usd']:.4f} | Total cost: ${ns['total_cost_usd']:.4f}
- Failure rate: {ns['failure_rate']*100:.0f}%"""
        if ns["common_errors"]:
            node_analysis += f"\n- Common errors: {', '.join(ns['common_errors'][:2])}"

    # Include the most recent log's node records for context
    recent_log = logs[-1] if logs else {}
    recent_nodes_yaml = ""
    if recent_log.get("node_records"):
        records = recent_log["node_records"][:10]  # Cap at 10 nodes
        recent_nodes_yaml = yaml.dump(records, default_flow_style=False, allow_unicode=True)

    goal_section = f"\n## User's Goal\n{goal}\n" if goal else ""

    return f"""You are an OSOP workflow optimizer. Analyze the execution data below and produce an optimized .osop workflow definition.

## Execution Summary
- Total runs analyzed: {stats['total_runs']}
- Average run duration: {stats['avg_duration_ms']}ms
- Total cost across all runs: ${stats['total_cost_usd']:.4f}
- Run outcomes: {stats['run_statuses']}

## Per-Node Analysis
{node_analysis}
{base_section}
## Most Recent Execution (node records)

```yaml
{recent_nodes_yaml}
```
{goal_section}
## Your Task

Based on the execution data, produce an optimized .osop workflow definition that:

1. **Identifies patterns**: What steps are consistently slow, expensive, or failing?
2. **Suggests structural changes**: Can any sequential steps run in parallel? Should any steps be split or merged?
3. **Adds resilience**: Add retry policies to nodes that fail frequently. Add fallback edges for critical paths.
4. **Optimizes cost**: Suggest cheaper models or shorter prompts where output quality allows.
5. **Adds missing safeguards**: Timeouts on slow nodes, approval gates on risky operations.

Output ONLY valid OSOP YAML (osop_version: "2.0"). Include:
- A clear `description` explaining what was optimized and why
- Comments (# lines) explaining each optimization decision
- All nodes and edges from the original, plus any new ones

Start your response with ```yaml and end with ```.
"""


def synthesize(
    log_paths: list[str] | None = None,
    log_contents: list[str] | None = None,
    base_osop_path: str | None = None,
    base_osop_content: str | None = None,
    goal: str = "",
    provider: str = "anthropic",
    model: str = "",
    prompt_only: bool = False,
) -> dict[str, Any]:
    """Synthesize an optimized .osop from multiple execution logs.

    Args:
        log_paths: List of paths to .osoplog.yaml files
        log_contents: List of YAML strings (alternative to paths)
        base_osop_path: Optional existing .osop to use as starting point
        base_osop_content: Optional .osop YAML string
        goal: Optional user goal/instruction for the optimization
        provider: LLM provider (anthropic or openai)
        model: LLM model to use

    Returns:
        {
            "status": "completed" | "failed",
            "stats": {...},  # aggregated execution stats
            "optimized_yaml": str,  # the new .osop content
            "insights": str,  # what the AI found
            "cost_usd": float,
        }
    """
    # Load logs
    logs = []
    if log_paths:
        logs = _load_logs(log_paths)
    if log_contents:
        for content in log_contents:
            try:
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    logs.append(data)
            except Exception:
                continue

    if not logs:
        return {
            "status": "failed",
            "error": "No valid .osoplog files provided. Pass log_paths or log_contents.",
            "stats": {},
            "optimized_yaml": None,
            "insights": None,
        }

    # Load base .osop if provided
    base_osop = None
    if base_osop_path:
        try:
            _, base_osop = load_yaml(file_path=base_osop_path)
        except Exception:
            pass
    elif base_osop_content:
        try:
            _, base_osop = load_yaml(content=base_osop_content)
        except Exception:
            pass

    # Aggregate stats
    stats = _aggregate_stats(logs)

    # Build prompt
    prompt = _build_synthesis_prompt(logs, stats, base_osop, goal)

    # Prompt-only mode: return the prompt for external LLM use (e.g., Claude Code itself)
    if prompt_only:
        return {
            "status": "prompt_ready",
            "stats": stats,
            "prompt": prompt,
            "optimized_yaml": None,
            "insights": "Use this prompt with any LLM to generate the optimized workflow.",
            "logs_analyzed": len(logs),
        }

    # Call LLM
    try:
        from .llm_client import call_llm
        result = call_llm(
            provider=provider,
            model=model or ("claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o"),
            system_prompt=(
                "You are an expert workflow optimizer. You analyze execution logs and produce "
                "optimized OSOP workflow definitions. Be specific about what you changed and why. "
                "Output valid YAML only."
            ),
            user_message=prompt,
            temperature=0.3,  # lower for more consistent output
            max_tokens=4096,
        )

        content = result["content"]

        # Extract YAML from response
        optimized_yaml = content
        if "```yaml" in content:
            start = content.index("```yaml") + 7
            end = content.index("```", start) if "```" in content[start:] else len(content)
            optimized_yaml = content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start) if "```" in content[start:] else len(content)
            optimized_yaml = content[start:end].strip()

        # Extract insights (text before or after YAML)
        insights = content
        if "```yaml" in content:
            before = content[:content.index("```yaml")].strip()
            after_idx = content.index("```", content.index("```yaml") + 7) + 3
            after = content[after_idx:].strip() if after_idx < len(content) else ""
            insights = (before + "\n" + after).strip()

        # Validate the generated YAML
        try:
            yaml.safe_load(optimized_yaml)
        except Exception:
            insights += "\n\nWARNING: Generated YAML may have syntax issues. Review before using."

        return {
            "status": "completed",
            "stats": stats,
            "optimized_yaml": optimized_yaml,
            "insights": insights or "See the optimized workflow above.",
            "cost_usd": result.get("cost_usd", 0),
            "model": result.get("model", ""),
            "logs_analyzed": len(logs),
        }

    except Exception as e:
        return {
            "status": "failed",
            "error": str(e),
            "stats": stats,
            "optimized_yaml": None,
            "insights": None,
        }
