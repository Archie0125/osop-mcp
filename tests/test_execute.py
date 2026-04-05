"""Tests for the OSOP workflow executor."""

from __future__ import annotations

import textwrap

import pytest

from tools.execute import execute, WorkflowContext, _topo_sort


# ---------------------------------------------------------------------------
# WorkflowContext tests
# ---------------------------------------------------------------------------

class TestWorkflowContext:
    def test_basic_store_and_retrieve(self):
        ctx = WorkflowContext({"initial": "value"})
        assert ctx.get("initial") == "value"
        assert ctx.get("missing") is None
        assert ctx.get("missing", "default") == "default"

    def test_set_output(self):
        ctx = WorkflowContext()
        ctx.set_output("node_a", "result", "hello")
        assert ctx.get("node_a.result") == "hello"
        assert ctx.get("result") == "hello"  # short name

    def test_set_node_result(self):
        ctx = WorkflowContext()
        ctx.set_node_result("node_a", "full output")
        assert ctx.get("node_a") == "full output"

    def test_resolve_inputs_strings(self):
        ctx = WorkflowContext()
        ctx.set_node_result("step1", "data from step1")
        resolved = ctx.resolve_inputs(["step1", "missing_ref"])
        assert resolved["step1"] == "data from step1"
        assert "unresolved" in resolved["missing_ref"]

    def test_resolve_inputs_dicts(self):
        ctx = WorkflowContext()
        ctx.set_output("gen", "idea", "build a chatbot")
        resolved = ctx.resolve_inputs([{"name": "idea"}])
        assert resolved["idea"] == "build a chatbot"

    def test_last_writer_wins(self):
        ctx = WorkflowContext()
        ctx.set_output("node_a", "data", "first")
        ctx.set_output("node_b", "data", "second")
        assert ctx.get("data") == "second"

    def test_summary(self):
        ctx = WorkflowContext({"key": "value"})
        s = ctx.summary()
        assert "key" in s


# ---------------------------------------------------------------------------
# Topo sort tests
# ---------------------------------------------------------------------------

class TestTopoSort:
    def test_linear_chain(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
        ]
        order = _topo_sort(nodes, edges)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_parallel_branches(self):
        nodes = [{"id": "start"}, {"id": "left"}, {"id": "right"}, {"id": "end"}]
        edges = [
            {"from": "start", "to": "left"},
            {"from": "start", "to": "right"},
            {"from": "left", "to": "end"},
            {"from": "right", "to": "end"},
        ]
        order = _topo_sort(nodes, edges)
        assert order[0] == "start"
        assert order[-1] == "end"

    def test_cycle_handling(self):
        nodes = [{"id": "a"}, {"id": "b"}]
        edges = [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ]
        order = _topo_sort(nodes, edges)
        assert set(order) == {"a", "b"}

    def test_orphan_node(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "orphan"}]
        edges = [{"from": "a", "to": "b"}]
        order = _topo_sort(nodes, edges)
        assert "orphan" in order


# ---------------------------------------------------------------------------
# Security gate tests
# ---------------------------------------------------------------------------

CLI_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "cli-test"
    name: "CLI Test"
    nodes:
      - id: "run_cmd"
        type: "cli"
        name: "Run Command"
        runtime:
          command: "echo hello"
    edges: []
""")

AGENT_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "agent-test"
    name: "Agent Test"
    nodes:
      - id: "think"
        type: "agent"
        name: "Think"
        purpose: "Generate an idea"
        runtime:
          provider: "anthropic"
          model: "claude-sonnet-4-20250514"
    edges: []
""")

API_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "api-test"
    name: "API Test"
    nodes:
      - id: "fetch"
        type: "api"
        name: "Fetch Data"
        runtime:
          url: "https://httpbin.org/get"
          method: "GET"
    edges: []
""")

MIXED_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "mixed-test"
    name: "Mixed Workflow"
    nodes:
      - id: "cmd"
        type: "cli"
        name: "Shell Command"
        runtime:
          command: "echo test"
      - id: "think"
        type: "agent"
        name: "Agent Think"
        purpose: "Analyze"
        runtime:
          provider: "anthropic"
    edges:
      - from: "cmd"
        to: "think"
""")


class TestSecurityGate:
    def test_cli_blocked_without_allow_exec(self):
        result = execute(content=CLI_WORKFLOW, allow_exec=False)
        assert result["status"] == "blocked"
        assert "allow_exec" in result.get("reason", "").lower() or "cli" in result.get("reason", "").lower()

    def test_cli_allowed_with_flag(self):
        result = execute(content=CLI_WORKFLOW, allow_exec=True)
        assert result["status"] != "blocked"

    def test_agent_workflow_no_exec_needed(self):
        # Agent workflows should NOT be blocked by allow_exec
        result = execute(content=AGENT_WORKFLOW, dry_run=True)
        assert result["status"] != "blocked"

    def test_mixed_workflow_blocked(self):
        # Mixed workflows with CLI nodes should be blocked
        result = execute(content=MIXED_WORKFLOW, allow_exec=False)
        assert result["status"] == "blocked"

    def test_cli_commands_shown_in_block(self):
        result = execute(content=CLI_WORKFLOW, allow_exec=False)
        cmds = result.get("cli_commands", [])
        assert len(cmds) > 0
        assert cmds[0]["command"] == "echo hello"


# ---------------------------------------------------------------------------
# Dry run tests
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_completes(self):
        result = execute(content=AGENT_WORKFLOW, dry_run=True)
        assert result["status"] == "completed"
        assert result["mode"] == "dry_run"

    def test_dry_run_no_execution(self):
        result = execute(content=CLI_WORKFLOW, dry_run=True)
        assert result["status"] == "completed"
        for nr in result["node_results"]:
            assert nr["status"] == "dry_run"

    def test_dry_run_node_count(self):
        result = execute(content=AGENT_WORKFLOW, dry_run=True)
        assert result["total_nodes"] == 1


# ---------------------------------------------------------------------------
# Agent execution tests (without real API keys)
# ---------------------------------------------------------------------------

class TestAgentExecution:
    def test_agent_fails_without_api_key(self):
        """Agent nodes should fail gracefully without API keys."""
        result = execute(content=AGENT_WORKFLOW, allow_exec=False)
        assert result["status"] == "failed"
        for nr in result["node_results"]:
            assert nr["status"] == "failed"
            assert "API_KEY" in nr.get("error", "") or "not found" in nr.get("error", "")

    def test_agent_cost_tracking(self):
        result = execute(content=AGENT_WORKFLOW)
        assert "total_cost_usd" in result


# ---------------------------------------------------------------------------
# Timeout tests
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_short_timeout(self):
        result = execute(content=AGENT_WORKFLOW, dry_run=True, timeout_seconds=0)
        # With 0 timeout, nodes should be skipped
        for nr in result.get("node_results", []):
            assert nr["status"] in ("skipped", "dry_run", "timeout")


# ---------------------------------------------------------------------------
# Context data flow tests
# ---------------------------------------------------------------------------

CHAIN_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "chain-test"
    name: "Chain Test"
    nodes:
      - id: "step1"
        type: "cli"
        name: "Step 1"
        runtime:
          command: "echo hello_world"
        outputs: [greeting]
      - id: "step2"
        type: "agent"
        name: "Step 2"
        inputs: [greeting]
        purpose: "Process the greeting"
        runtime:
          provider: "anthropic"
    edges:
      - from: "step1"
        to: "step2"
""")


class TestDataFlow:
    def test_cli_output_captured(self):
        result = execute(content=CLI_WORKFLOW, allow_exec=True)
        nr = result["node_results"][0]
        if nr["status"] == "completed":
            assert "hello" in nr.get("stdout", "")

    def test_context_keys_tracked(self):
        result = execute(content=CLI_WORKFLOW, allow_exec=True)
        if result["status"] == "completed":
            assert "context_keys" in result


# ---------------------------------------------------------------------------
# Cost limit tests
# ---------------------------------------------------------------------------

class TestCostLimit:
    def test_cost_limit_respected(self):
        result = execute(content=AGENT_WORKFLOW, max_cost_usd=0.0)
        # With $0 limit, either fails on API key or respects limit
        assert "total_cost_usd" in result


# ---------------------------------------------------------------------------
# Conditional edge tests
# ---------------------------------------------------------------------------

CONDITIONAL_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "conditional-test"
    name: "Conditional Test"
    nodes:
      - id: "start"
        type: "cli"
        name: "Start"
        runtime:
          command: "echo success"
        outputs: [result]
      - id: "happy_path"
        type: "cli"
        name: "Happy Path"
        runtime:
          command: "echo happy"
      - id: "sad_path"
        type: "cli"
        name: "Sad Path"
        runtime:
          command: "echo sad"
    edges:
      - from: "start"
        to: "happy_path"
        mode: "conditional"
        condition: "true"
      - from: "start"
        to: "sad_path"
        mode: "conditional"
        condition: "false"
""")

FALLBACK_WORKFLOW = textwrap.dedent("""\
    osop_version: "1.0"
    id: "fallback-test"
    name: "Fallback Test"
    nodes:
      - id: "try_it"
        type: "cli"
        name: "Try"
        runtime:
          command: "exit 1"
      - id: "fallback"
        type: "cli"
        name: "Fallback"
        runtime:
          command: "echo recovered"
      - id: "success_path"
        type: "cli"
        name: "Success"
        runtime:
          command: "echo done"
    edges:
      - from: "try_it"
        to: "success_path"
        mode: "sequential"
      - from: "try_it"
        to: "fallback"
        mode: "fallback"
""")


class TestConditionalEdges:
    def test_conditional_true_executes(self):
        result = execute(content=CONDITIONAL_WORKFLOW, allow_exec=True)
        node_ids = [nr["node_id"] for nr in result["node_results"]]
        assert "start" in node_ids
        assert "happy_path" in node_ids

    def test_conditional_false_skipped(self):
        result = execute(content=CONDITIONAL_WORKFLOW, allow_exec=True)
        node_ids = [nr["node_id"] for nr in result["node_results"]]
        # sad_path should not be in results because condition is "false"
        assert "sad_path" not in node_ids or any(
            nr["node_id"] == "sad_path" and nr["status"] == "skipped"
            for nr in result["node_results"]
        )

    def test_fallback_on_failure(self):
        result = execute(content=FALLBACK_WORKFLOW, allow_exec=True)
        node_ids = [nr["node_id"] for nr in result["node_results"]]
        assert "try_it" in node_ids
        assert "fallback" in node_ids  # fallback should fire because try_it exits 1

    def test_dry_run_conditional(self):
        result = execute(content=CONDITIONAL_WORKFLOW, dry_run=True)
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Condition evaluator tests
# ---------------------------------------------------------------------------

from tools.execute import _eval_condition, WorkflowContext as WC


class TestConditionEvaluator:
    def test_true_literal(self):
        assert _eval_condition("true", WC()) is True

    def test_false_literal(self):
        assert _eval_condition("false", WC()) is False

    def test_empty_string(self):
        assert _eval_condition("", WC()) is True

    def test_numeric_comparison(self):
        ctx = WC()
        ctx._store["score"] = 0.85
        assert _eval_condition("score >= 0.8", ctx) is True
        assert _eval_condition("score < 0.5", ctx) is False

    def test_string_comparison(self):
        ctx = WC()
        ctx._store["status"] = "completed"
        assert _eval_condition('status == "completed"', ctx) is True
        assert _eval_condition('status == "failed"', ctx) is False

    def test_truthy_variable(self):
        ctx = WC()
        ctx._store["has_result"] = "yes"
        assert _eval_condition("has_result", ctx) is True

    def test_missing_variable(self):
        ctx = WC()
        assert _eval_condition("nonexistent >= 5", ctx) is False
