"""OSOP MCP Server — Init, Validate, Record, Replay, Log, Diff, Optimize, View.

Eight tools mirroring the `osop` CLI. `osop.replay` and `osop.log` are the
durable-streaming and transcript-synthesis entry points added in v1.0.
"""

from __future__ import annotations

import json
import subprocess
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


def _run_osop_cli(args: list[str], cwd: str | None = None) -> dict:
    """Dispatch a tool by shelling out to the installed `osop` CLI.

    Used for commands that don't have a direct Python entry point on
    the server side yet (init, replay, log, view). Returns a dict with
    exit code + stdout + stderr so MCP clients can surface failures.
    """
    try:
        proc = subprocess.run(
            ["osop", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=600,
        )
    except FileNotFoundError:
        return {
            "error": "osop CLI not found on PATH. Install with 'pip install -e osop/' from the OSOP project root.",
            "args": args,
        }
    except subprocess.TimeoutExpired:
        return {"error": "osop CLI timed out after 600s", "args": args}

    return {
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-2000:],
        "status": "ok" if proc.returncode == 0 else "failed",
    }

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
        if name == "osop.init":
            project_dir = arguments.get("project_dir")
            result = _run_osop_cli(["init"], cwd=project_dir)

        elif name == "osop.replay":
            args = ["replay", arguments["file_path"]]
            if arguments.get("allow_exec"):
                args.append("--allow-exec")
            if arguments.get("interactive"):
                args.append("--interactive")
            if arguments.get("continue_on_error"):
                args.append("--continue-on-error")
            if arguments.get("output_dir"):
                args.extend(["-o", arguments["output_dir"]])
            if arguments.get("timeout_seconds"):
                args.extend(["--timeout", str(arguments["timeout_seconds"])])
            result = _run_osop_cli(args)

        elif name == "osop.log":
            args = ["log"]
            if arguments.get("source"):
                args.append(arguments["source"])
            if arguments.get("short_desc"):
                args.extend(["-d", arguments["short_desc"]])
            if arguments.get("output_dir"):
                args.extend(["-o", arguments["output_dir"]])
            for tag in arguments.get("tags", []) or []:
                args.extend(["--tag", tag])
            result = _run_osop_cli(args, cwd=arguments.get("project_dir"))

        elif name == "osop.view":
            args = ["view", arguments["file_path"]]
            if arguments.get("output_path"):
                args.extend(["-o", arguments["output_path"]])
            if arguments.get("lang"):
                args.extend(["--lang", arguments["lang"]])
            result = _run_osop_cli(args)

        elif name == "osop.validate":
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
