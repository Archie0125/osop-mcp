"""OSOP MCP Server — Expose OSOP workflow operations as MCP tools for AI agents."""

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
from tools.render import render
from tools.risk_assess import risk_assess
from tools.optimize import optimize
from tools.convert import convert as convert_workflow
from tools.diff import diff_workflows
from tools.execute import execute as execute_workflow
from tools.notion import osop_to_notion
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
            )

        elif name == "osop.render":
            result = render(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                format=arguments.get("format", "mermaid"),
                direction=arguments.get("direction", "TB"),
            )

        elif name == "osop.risk_assess":
            result = risk_assess(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
            )

        elif name == "osop.run":
            result = execute_workflow(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                inputs=arguments.get("inputs"),
                dry_run=arguments.get("dry_run", False),
                timeout_seconds=arguments.get("timeout_seconds", 300),
            )

        elif name == "osop.test":
            raw, parsed = load_yaml(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
            )
            tests = parsed.get("tests", [])
            result = {
                "total": len(tests),
                "passed": len(tests),
                "failed": 0,
                "results": [
                    {"name": t.get("name", f"test_{i}"), "status": "passed"}
                    for i, t in enumerate(tests)
                    if isinstance(t, dict)
                ],
                "message": "Test execution is mock-only in this version.",
            }

        elif name == "osop.optimize":
            result = optimize(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                apply=arguments.get("apply", False),
                run_history=arguments.get("run_history"),
            )

        elif name == "osop.report":
            raw, parsed = load_yaml(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
            )
            fmt = arguments.get("format", "text")
            wf_name = parsed.get("name", "Workflow")
            nodes = parsed.get("nodes", [])

            if fmt == "text":
                lines = [f"=== OSOP Report: {wf_name} ===", ""]
                lines.append(f"Nodes: {len(nodes)}")
                lines.append(f"Edges: {len(parsed.get('edges', []))}")
                lines.append("")
                for n in nodes:
                    if isinstance(n, dict):
                        lines.append(f"  [{n.get('type', '?')}] {n.get('id', '?')}: {n.get('name', '')}")
                result = {"format": "text", "report": "\n".join(lines)}
            else:
                result = {"format": "html", "report": f"<h1>OSOP Report: {wf_name}</h1><p>{len(nodes)} nodes</p>"}

        elif name in ("osop.import", "osop.export"):
            source_fmt = arguments.get("source_format")
            target_fmt = arguments.get("target_format")
            result = convert_workflow(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                source_format=source_fmt,
                target_format=target_fmt,
            )

        elif name == "osop.convert":
            result = convert_workflow(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
                source_format=arguments.get("source_format"),
                target_format=arguments.get("target_format"),
            )

        elif name == "osop.diff":
            result = diff_workflows(
                content_a=arguments.get("content_a"),
                file_path_a=arguments.get("file_path_a"),
                content_b=arguments.get("content_b"),
                file_path_b=arguments.get("file_path_b"),
            )

        elif name == "osop.notion":
            result = osop_to_notion(
                content=arguments.get("content"),
                file_path=arguments.get("file_path"),
            )

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
