# OSOP MCP Server

**5 focused tools** for AI agents to work with OSOP workflows.

Any MCP-compatible client (Claude, Cursor, Windsurf) becomes workflow-aware.

## Tools

| Tool | Description |
|------|-------------|
| `osop.validate` | Validate `.osop.yaml` against Core (4 types) or Full (12 types) schema |
| `osop.render` | Render workflow as Mermaid or ASCII diagram |
| `osop.report` | Generate HTML or text reports from workflow + execution log |
| `osop.diff` | Structural comparison of two workflows or execution logs |
| `osop.risk_assess` | Security risk analysis — score 0-100 with actionable findings |

## Installation

```bash
pip install osop-mcp
```

## Usage

### Claude Code

Add to your project's `.mcp.json`:

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

### Claude Desktop

Add to `claude_desktop_config.json`:

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

### Docker

```bash
docker build -t osop-mcp .
docker run -i osop-mcp
```

## Quick Example

Once installed, ask your AI agent:

> "Validate my deployment workflow and check for security risks"

The agent will:
1. Use `osop.validate` to check schema compliance
2. Use `osop.risk_assess` to identify unguarded destructive ops, missing approvals, exposed secrets
3. Use `osop.render` to show you a visual diagram

## What is OSOP?

OSOP is the standard format for describing and logging AI agent workflows.

- **Spec**: [osop-spec](https://github.com/Archie0125/osop-spec) — Protocol specification
- **Editor**: [osop-editor](https://osop-editor.vercel.app) — Visual workflow editor
- **Examples**: [osop-examples](https://github.com/Archie0125/osop-examples) — Workflow templates

## License

Apache License 2.0
