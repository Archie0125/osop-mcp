# OSOP MCP Server

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![OSOP Compatible](https://img.shields.io/badge/OSOP-compatible-blue)](https://osop.ai)

MCP (Model Context Protocol) server that exposes OSOP workflow operations as tools for AI agents. Any MCP-compatible client (Claude Desktop, Claude Code, OpenClaw, Cursor, etc.) can validate, run, render, test, optimize, and **assess security risks** of OSOP workflows.

Website: [osop.ai](https://osop.ai) | Editor: [osop-editor.vercel.app](https://osop-editor.vercel.app)

## Tools

| Tool | Description |
|------|-------------|
| `osop.validate` | Validate an `.osop.yaml` file against the OSOP schema. Returns errors and warnings. |
| `osop.risk_assess` | **Analyze workflow for security risks** — permission gaps, missing approval gates, destructive commands, cost exposure. Returns risk score (0-100) and actionable findings. |
| `osop.run` | Execute a workflow with given inputs. Supports dry-run mode. |
| `osop.render` | Render a workflow as Mermaid or ASCII diagram. |
| `osop.test` | Run test cases defined in the workflow and report pass/fail results. |
| `osop.optimize` | Analyze a workflow for redundancies, parallelization opportunities, and bottlenecks. |
| `osop.report` | Generate HTML or text reports from workflow + optional execution log. |
| `osop.import` | Convert external formats (GitHub Actions, BPMN, Airflow DAG) into OSOP. |
| `osop.export` | Convert an OSOP workflow to an external format. |

## Installation

```bash
pip install osop-mcp
```

## Usage

### Standalone

```bash
python -m osop_mcp
```

The server listens on stdio by default (MCP standard transport).

### Docker

```bash
docker build -t osop-mcp .
docker run -i osop-mcp
```

### Claude Desktop / Claude Code

Add to your `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%/Claude/`):

```json
{
  "mcpServers": {
    "osop": {
      "command": "python",
      "args": ["-m", "osop_mcp"],
      "env": {}
    }
  }
}
```

For **Claude Code**, add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "osop": {
      "command": "python",
      "args": ["-m", "osop_mcp"]
    }
  }
}
```

### Docker-based Configuration

```json
{
  "mcpServers": {
    "osop": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "osop-mcp"]
    }
  }
}
```

## Quick Start: Risk Assessment

Once installed, ask your AI agent:

> "Analyze the security risks of my deployment workflow"

The agent will use `osop.risk_assess` to:
1. Walk the workflow DAG and identify high-risk nodes
2. Check for missing approval gates before destructive operations
3. Flag overly broad permissions (`write:*`, `admin:*`)
4. Detect destructive CLI commands (`rm -rf`, `kubectl delete`, `terraform destroy`)
5. Calculate cost exposure from agent nodes
6. Return a risk score (0-100) with verdict: `safe` / `caution` / `warning` / `danger`

Example output:
```json
{
  "overall_score": 72,
  "verdict": "danger",
  "total_findings": 5,
  "findings": [
    {
      "severity": "critical",
      "title": "CRITICAL risk node without approval gate",
      "node_id": "deploy-prod",
      "suggestion": "Add approval_gate with required: true before this node."
    }
  ]
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OSOP_MCP_TRANSPORT` | Transport protocol (`stdio` or `sse`) | `stdio` |
| `OSOP_MCP_PORT` | Port for SSE transport | `8080` |
| `OSOP_LOG_LEVEL` | Logging level | `INFO` |

## Development

```bash
git clone https://github.com/Archie0125/osop-mcp.git
cd osop-mcp
pip install -e ".[dev]"
pytest
```

## What is OSOP?

OSOP (Open Standard Operating Protocol) is the OpenAPI of workflows. It standardizes how workflows, SOPs, and automation pipelines are defined, validated, and executed — across AI agents, CI/CD tools, and enterprise processes.

- **Spec**: [osop-spec](https://github.com/Archie0125/osop-spec) — Protocol specification v1.0
- **Editor**: [osop-editor](https://osop-editor.vercel.app) — Visual editor with risk analysis
- **Examples**: [osop-examples](https://github.com/Archie0125/osop-examples) — 30+ workflow templates

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
