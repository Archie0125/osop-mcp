"""OSOP MCP Server — Validate, Record, Diff, Optimize AI agent workflows.

Four tools: validate, record, diff, optimize.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Add parent to path for tool imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate import validate
from tools.diff import diff_workflows, diff_logs
from tools.common import load_yaml

# Load tool definitions from tools.json
_TOOLS_PATH = Path(__file__).resolve().parent.parent / "tools.json"
_TOOL_DEFS: list[dict] = []
if _TOOLS_PATH.exists():
    _TOOL_DEFS = json.loads(_TOOLS_PATH.read_text(encoding="utf-8")).get("tools", [])

app = Server("osop-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return all available OSOP tools."""
    return [
        Tool(
            name=td["name"],
            description=td.get("description", ""),
            inputSchema=td.get("inputSchema", {}),
        )
        for td in _TOOL_DEFS
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch tool calls to implementations."""
    try:
        if name == "osop.validate":
            result = validate(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                strict=arguments.get("strict", False),
                schema_variant=arguments.get("schema_variant", "core"),
            )

        elif name == "osop.record":
            # Validate internally first
            raw, parsed = load_yaml(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
            )
            val_result = validate(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                schema_variant="core",
            )
            if not val_result.get("valid"):
                result = {"status": "invalid", "errors": val_result.get("errors", [])}
            else:
                # Try real execution
                try:
                    from tools.execute import execute
                    result = execute(
                        file_path=arguments.get("file_path"),
                        content=arguments.get("content"),
                        dry_run=arguments.get("dry_run", False),
                        allow_exec=arguments.get("allow_exec", False),
                    )
                except ImportError:
                    # Mock execution — return workflow structure as record
                    nodes = parsed.get("nodes", [])
                    result = {
                        "status": "mock",
                        "workflow_id": parsed.get("id"),
                        "nodes_count": len(nodes),
                        "node_ids": [n.get("id") for n in nodes if isinstance(n, dict)],
                        "message": "Executor not available. Workflow validated successfully.",
                    }

        elif name == "osop.diff":
            # Auto-detect log vs workflow
            file_a = arguments.get("file_path_a", "")
            is_log = file_a.endswith(".osoplog.yaml") or file_a.endswith(".osoplog.yml")

            if is_log:
                result = diff_logs(
                    content_a=arguments.get("content_a"),
                    file_path_a=arguments.get("file_path_a"),
                    content_b=arguments.get("content_b"),
                    file_path_b=arguments.get("file_path_b"),
                )
            else:
                result = diff_workflows(
                    content_a=arguments.get("content_a"),
                    file_path_a=arguments.get("file_path_a"),
                    content_b=arguments.get("content_b"),
                    file_path_b=arguments.get("file_path_b"),
                )

        elif name == "osop.optimize":
            try:
                from tools.synthesize import synthesize
                result = synthesize(
                    log_paths=arguments.get("log_paths", []),
                    base_osop_path=arguments.get("base_osop_path"),
                    goal=arguments.get("goal", ""),
                    prompt_only=arguments.get("prompt_only", False),
                )
            except ImportError:
                result = {"error": "Synthesize module not available. Ensure osop-mcp is properly installed."}

        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        result = {"error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def main():
    """Run the OSOP MCP server via stdio."""
    async with stdio_server() as (read_stream, write_stream):
        init_options = app.create_initialization_options()
        await app.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
