# OSOP MCP Server

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)

MCP (Model Context Protocol) server that exposes OSOP workflow operations as tools for AI agents. Any MCP-compatible client (Claude Desktop, OpenClaw, Cursor, etc.) can validate, run, render, test, optimize, import, and export OSOP workflows.

Website: [osop.ai](https://osop.ai) | GitHub: [github.com/osop/osop-mcp](https://github.com/osop/osop-mcp)

## Tools

| Tool | Description |
|------|-------------|
| `osop.validate` | Validate an `.osop.yaml` file against the OSOP schema. Returns errors and warnings. |
| `osop.run` | Execute a workflow with given inputs. Supports dry-run mode. |
| `osop.render` | Render a workflow as Mermaid, ASCII, or SVG diagram. |
| `osop.test` | Run test cases defined in the workflow and report pass/fail results. |
| `osop.optimize` | Analyze a workflow for redundancies, parallelization opportunities, and bottlenecks. |
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

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

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

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OSOP_MCP_TRANSPORT` | Transport protocol (`stdio` or `sse`) | `stdio` |
| `OSOP_MCP_PORT` | Port for SSE transport | `8080` |
| `OSOP_LOG_LEVEL` | Logging level | `INFO` |

## Development

```bash
git clone https://github.com/osop/osop-mcp.git
cd osop-mcp
pip install -e ".[dev]"
pytest
```

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
