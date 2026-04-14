# awesome-mcp-servers PR Submission

## Entry to add

### Workflow & Automation

- **[OSOP MCP Server](https://github.com/Archie0125/osop-mcp)** — 4 tools for AI agent workflows: validate schemas, record executions, diff workflows, and optimize from logs. The standard format for describing and logging what AI agents do.

## PR Details

**Targets:**
- https://github.com/punkpeye/awesome-mcp-servers
- https://github.com/TensorBlock/awesome-mcp-servers
- https://github.com/wong2/awesome-mcp-servers

**Title:** Add OSOP MCP Server — AI agent workflow validation, visualization, and risk analysis

**Body:**

Adds the OSOP MCP Server to the Workflow & Automation section.

OSOP is the standard format for describing and logging AI agent workflows. Two YAML files: `.osop` (what should happen) and `.osoplog` (what actually happened).

The MCP server provides 4 tools:

| Tool | What it does |
|------|-------------|
| `osop.validate` | Validate workflows against Core (4 types) or Full (12 types) schema |
| `osop.render` | Generate Mermaid or ASCII diagrams |
| `osop.report` | Generate HTML/text reports from workflow + execution log |
| `osop.diff` | Structural comparison of two workflows |
| `osop.risk_assess` | Security risk score (0-100) with actionable findings |

Works with Claude Desktop, Claude Code, Cursor, Windsurf, and any MCP client.

- [GitHub](https://github.com/Archie0125/osop-mcp)
- [Spec](https://github.com/Archie0125/osop-spec)
- [Visual Editor](https://osop-editor.vercel.app)
