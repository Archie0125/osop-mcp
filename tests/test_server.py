"""Tests for server/main.py — MCP server tool listing and dispatch."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from server.main import list_tools, call_tool, _TOOL_DEFS, app


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------

class TestListTools:
    """Tests for the list_tools handler."""

    async def test_list_tools_returns_list(self):
        tools = await list_tools()
        assert isinstance(tools, list)

    async def test_list_tools_not_empty(self):
        assert len(_TOOL_DEFS) > 0, "tools.json should define at least one tool"
        tools = await list_tools()
        assert len(tools) > 0

    async def test_each_tool_has_name(self):
        tools = await list_tools()
        for tool in tools:
            assert hasattr(tool, "name")
            assert tool.name.startswith("osop.")

    async def test_each_tool_has_description(self):
        tools = await list_tools()
        for tool in tools:
            assert hasattr(tool, "description")
            assert len(tool.description) > 0

    async def test_each_tool_has_input_schema(self):
        tools = await list_tools()
        for tool in tools:
            assert hasattr(tool, "inputSchema")
            assert isinstance(tool.inputSchema, dict)

    async def test_known_tools_present(self):
        tools = await list_tools()
        names = {t.name for t in tools}
        expected = {"osop.validate", "osop.render", "osop.risk_assess", "osop.optimize"}
        assert expected.issubset(names)


# ---------------------------------------------------------------------------
# Tool definitions loading
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    """Tests for tool definition loading from tools.json."""

    def test_tool_defs_loaded(self):
        assert isinstance(_TOOL_DEFS, list)
        assert len(_TOOL_DEFS) > 0

    def test_each_def_has_required_fields(self):
        for td in _TOOL_DEFS:
            assert "name" in td
            assert "inputSchema" in td

    def test_tools_json_exists(self):
        tools_json = Path(__file__).resolve().parent.parent / "tools.json"
        assert tools_json.exists()


# ---------------------------------------------------------------------------
# Tool dispatch — osop.validate
# ---------------------------------------------------------------------------

class TestCallToolValidate:
    """Tests for dispatching osop.validate via call_tool."""

    async def test_validate_returns_text_content(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.validate", {"content": VALID_WORKFLOW_YAML})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].type == "text"

    async def test_validate_result_is_json(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.validate", {"content": VALID_WORKFLOW_YAML})
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, dict)
        assert "valid" in parsed


# ---------------------------------------------------------------------------
# Tool dispatch — osop.render
# ---------------------------------------------------------------------------

class TestCallToolRender:
    """Tests for dispatching osop.render via call_tool."""

    async def test_render_mermaid(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.render", {
            "content": VALID_WORKFLOW_YAML,
            "format": "mermaid",
        })
        parsed = json.loads(result[0].text)
        assert parsed["format"] == "mermaid"
        assert "diagram" in parsed

    async def test_render_ascii(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.render", {
            "content": VALID_WORKFLOW_YAML,
            "format": "ascii",
        })
        parsed = json.loads(result[0].text)
        assert parsed["format"] == "ascii"


# ---------------------------------------------------------------------------
# Tool dispatch — osop.risk_assess
# ---------------------------------------------------------------------------

class TestCallToolRiskAssess:
    """Tests for dispatching osop.risk_assess via call_tool."""

    async def test_risk_assess_dispatch(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.risk_assess", {"content": VALID_WORKFLOW_YAML})
        parsed = json.loads(result[0].text)
        assert "overall_score" in parsed
        assert "verdict" in parsed


# ---------------------------------------------------------------------------
# Tool dispatch — osop.optimize
# ---------------------------------------------------------------------------

class TestCallToolOptimize:
    """Tests for dispatching osop.optimize via call_tool."""

    async def test_optimize_dispatch(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.optimize", {"content": VALID_WORKFLOW_YAML})
        parsed = json.loads(result[0].text)
        assert "suggestions" in parsed
        assert "suggestion_count" in parsed


# ---------------------------------------------------------------------------
# Tool dispatch — osop.run (mock)
# ---------------------------------------------------------------------------

class TestCallToolRun:
    """Tests for dispatching osop.run (mock execution)."""

    async def test_run_mock_mode(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.run", {"content": VALID_WORKFLOW_YAML, "dry_run": True})
        parsed = json.loads(result[0].text)
        assert parsed.get("mode") in ("mock", "live", "dry_run")
        assert parsed.get("total_nodes", parsed.get("nodes_executed", 0)) >= 1

    async def test_run_dry_run_mode(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.run", {"content": VALID_WORKFLOW_YAML, "dry_run": True})
        parsed = json.loads(result[0].text)
        assert parsed["mode"] == "dry_run"
        assert "completed" in parsed["status"]


# ---------------------------------------------------------------------------
# Tool dispatch — osop.test (mock)
# ---------------------------------------------------------------------------

class TestCallToolTest:
    """Tests for dispatching osop.test (mock test runner)."""

    async def test_test_dispatch(self):
        from tests.conftest import WORKFLOW_WITH_TESTS_YAML
        result = await call_tool("osop.test", {"content": WORKFLOW_WITH_TESTS_YAML})
        parsed = json.loads(result[0].text)
        assert parsed["total"] == 2
        assert parsed["passed"] == 2
        assert parsed["failed"] == 0

    async def test_test_no_tests(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.test", {"content": VALID_WORKFLOW_YAML})
        parsed = json.loads(result[0].text)
        assert parsed["total"] == 0


# ---------------------------------------------------------------------------
# Tool dispatch — osop.report
# ---------------------------------------------------------------------------

class TestCallToolReport:
    """Tests for dispatching osop.report."""

    async def test_report_text_format(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.report", {
            "content": VALID_WORKFLOW_YAML,
            "format": "text",
        })
        parsed = json.loads(result[0].text)
        assert parsed["format"] == "text"
        assert "Test Workflow" in parsed["report"]

    async def test_report_html_format(self):
        from tests.conftest import VALID_WORKFLOW_YAML
        result = await call_tool("osop.report", {
            "content": VALID_WORKFLOW_YAML,
            "format": "html",
        })
        parsed = json.loads(result[0].text)
        assert parsed["format"] == "html"
        assert "<h1>" in parsed["report"]


# ---------------------------------------------------------------------------
# Tool dispatch — unknown / not-yet-implemented
# ---------------------------------------------------------------------------

class TestCallToolEdgeCases:
    """Tests for error handling in tool dispatch."""

    async def test_unknown_tool_returns_error(self):
        result = await call_tool("osop.nonexistent", {})
        parsed = json.loads(result[0].text)
        assert "error" in parsed
        assert "Unknown tool" in parsed["error"]

    async def test_import_unsupported_format(self):
        result = await call_tool("osop.import", {"content": "x: 1", "source_format": "bpmn"})
        parsed = json.loads(result[0].text)
        assert "error" in parsed
        assert "bpmn" in parsed["error"].lower() or "unsupported" in parsed["error"].lower()

    async def test_export_unsupported_format(self):
        result = await call_tool("osop.export", {"content": "x: 1", "target_format": "bpmn"})
        parsed = json.loads(result[0].text)
        assert "error" in parsed
        assert "bpmn" in parsed["error"].lower() or "unsupported" in parsed["error"].lower()

    async def test_invalid_yaml_returns_error(self):
        result = await call_tool("osop.validate", {"content": "- bad\n- yaml\n"})
        parsed = json.loads(result[0].text)
        assert "error" in parsed

    async def test_missing_arguments_returns_error(self):
        result = await call_tool("osop.validate", {})
        parsed = json.loads(result[0].text)
        assert "error" in parsed
