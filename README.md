# OSOP MCP Server

**5 tools** for AI agents to validate, record, diff, optimize, and view OSOP workflows.

Any MCP-compatible client (Claude, Cursor, Windsurf) becomes workflow-aware.

## Tools

| Tool | Description |
|------|-------------|
| `osop.validate` | Validate `.osop.yaml` or `.osoplog.yaml` against schema |
| `osop.record` | Execute workflow, produce `.osoplog` execution record |
| `osop.diff` | Compare two workflows or execution logs |
| `osop.optimize` | Synthesize better workflow from multiple execution logs |
| `osop.view` | Render `.sop` into standalone HTML document |

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

## What is OSOP?

OSOP is the standard format for describing and logging AI agent workflows. 4 node types, 4 edge modes.

- **CLI**: `pip install osop` (validate, record, diff, optimize, view)
- **Spec**: [osop-spec](https://github.com/Archie0125/osop-spec)
- **Editor**: [osop-editor](https://osop-editor.vercel.app)

## License

Apache License 2.0
