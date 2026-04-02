"""Tests for tools/optimize.py — Workflow optimization suggestions."""

from __future__ import annotations

import json
import textwrap

import pytest

from tools.optimize import optimize, _find_sequential_chains, _check_independence


class TestOptimizeSuggestions:
    """Tests for optimization suggestion generation."""

    def test_returns_suggestions_list(self, valid_yaml):
        result = optimize(content=valid_yaml)
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)
        assert "suggestion_count" in result

    def test_suggestion_count_matches(self, valid_yaml):
        result = optimize(content=valid_yaml)
        assert result["suggestion_count"] == len(result["suggestions"])

    def test_missing_retry_detected(self, valid_yaml):
        """External-type nodes without retry_policy get add_retry suggestion."""
        result = optimize(content=valid_yaml)
        retry_suggestions = [s for s in result["suggestions"] if s["type"] == "add_retry"]
        # Both cli and api nodes lack retry_policy
        assert len(retry_suggestions) >= 1

    def test_missing_timeout_detected(self, valid_yaml):
        """External-type nodes without timeout_sec get optimize suggestion."""
        result = optimize(content=valid_yaml)
        timeout_suggestions = [s for s in result["suggestions"] if "timeout" in s.get("description", "").lower()]
        assert len(timeout_suggestions) >= 1

    def test_missing_fallback_on_high_risk(self, high_risk_yaml):
        """High-risk nodes without fallback get restructure suggestion."""
        result = optimize(content=high_risk_yaml)
        restructure = [s for s in result["suggestions"] if s["type"] == "restructure"]
        assert len(restructure) >= 1
        assert restructure[0]["priority"] == "high"

    def test_human_nodes_no_retry_suggestion(self):
        """Human-type nodes should not get retry suggestions."""
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "human-only"
            name: "Human Only"
            nodes:
              - id: "review"
                type: "human"
                name: "Review"
            edges: []
        """)
        result = optimize(content=yaml_str)
        retry_suggestions = [s for s in result["suggestions"] if s["type"] == "add_retry"]
        assert len(retry_suggestions) == 0


class TestOptimizeParallelDetection:
    """Tests for parallel opportunity detection."""

    def test_parallel_opportunity_detected(self, parallel_candidate_yaml):
        result = optimize(content=parallel_candidate_yaml)
        parallel = [s for s in result["suggestions"] if s["type"] == "parallelize"]
        assert len(parallel) >= 1
        assert "parallelize" in parallel[0]["description"].lower() or "parallel" in parallel[0]["description"].lower()

    def test_no_parallel_for_dependent_nodes(self):
        """Nodes with data dependencies should NOT get parallelization suggestions."""
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "dependent"
            name: "Dependent Chain"
            nodes:
              - id: "a"
                type: "api"
                name: "Get User"
                outputs:
                  - name: "user_id"
              - id: "b"
                type: "api"
                name: "Get Orders"
                inputs:
                  - name: "user_id"
                outputs:
                  - name: "orders"
              - id: "c"
                type: "api"
                name: "Process Orders"
                inputs:
                  - name: "orders"
            edges:
              - from: "a"
                to: "b"
                mode: "sequential"
              - from: "b"
                to: "c"
                mode: "sequential"
        """)
        result = optimize(content=yaml_str)
        parallel = [s for s in result["suggestions"] if s["type"] == "parallelize"]
        assert len(parallel) == 0

    def test_short_chain_not_suggested(self):
        """Chains shorter than 3 nodes should not trigger parallelize."""
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "short"
            name: "Short"
            nodes:
              - id: "a"
                type: "api"
                name: "A"
              - id: "b"
                type: "api"
                name: "B"
            edges:
              - from: "a"
                to: "b"
                mode: "sequential"
        """)
        result = optimize(content=yaml_str)
        parallel = [s for s in result["suggestions"] if s["type"] == "parallelize"]
        assert len(parallel) == 0


class TestOptimizeRunHistory:
    """Tests for optimization with run history."""

    def test_slow_steps_detected(self, parallel_candidate_yaml, run_history_json):
        result = optimize(content=parallel_candidate_yaml, run_history=run_history_json)
        slow = result["analysis"]["slow_steps"]
        assert len(slow) >= 1
        # Node "a" has avg ~7750ms which is > 5000ms threshold
        slow_ids = [s["node_id"] for s in slow]
        assert "a" in slow_ids

    def test_failure_hotspots_detected(self, parallel_candidate_yaml, run_history_json):
        result = optimize(content=parallel_candidate_yaml, run_history=run_history_json)
        hotspots = result["analysis"]["failure_hotspots"]
        assert len(hotspots) >= 1
        # Node "b" fails 100% of the time
        hotspot_ids = [h["node_id"] for h in hotspots]
        assert "b" in hotspot_ids

    def test_bottleneck_identified(self, parallel_candidate_yaml, run_history_json):
        """Nodes that are both slow and unreliable are bottlenecks."""
        # Node "b" is unreliable but fast; node "a" is slow but reliable
        # Need a node that's both slow AND unreliable
        history = json.dumps([{
            "node_records": [
                {"node_id": "a", "status": "FAILED", "duration_ms": 8000, "error": {"message": "timeout"}},
            ]
        }, {
            "node_records": [
                {"node_id": "a", "status": "FAILED", "duration_ms": 7000, "error": {"message": "timeout"}},
            ]
        }])
        result = optimize(content=parallel_candidate_yaml, run_history=history)
        bottlenecks = result["analysis"]["bottlenecks"]
        assert len(bottlenecks) >= 1

    def test_no_history_returns_empty_analysis(self, valid_yaml):
        result = optimize(content=valid_yaml)
        assert result["analysis"]["slow_steps"] == []
        assert result["analysis"]["failure_hotspots"] == []
        assert result["analysis"]["bottlenecks"] == []

    def test_invalid_json_history_gracefully_handled(self, valid_yaml):
        result = optimize(content=valid_yaml, run_history="not valid json")
        # Should not crash; history is just ignored
        assert "suggestions" in result

    def test_failure_hotspot_retry_priority(self, parallel_candidate_yaml, run_history_json):
        """Nodes that are failure hotspots should get high-priority retry suggestions."""
        result = optimize(content=parallel_candidate_yaml, run_history=run_history_json)
        retry_for_b = [
            s for s in result["suggestions"]
            if s["type"] == "add_retry" and "b" in s["target_node_ids"]
        ]
        assert len(retry_for_b) >= 1
        assert retry_for_b[0]["priority"] == "high"


class TestOptimizeApply:
    """Tests for the apply mode that generates modified YAML."""

    def test_apply_false_no_proposed_yaml(self, valid_yaml):
        result = optimize(content=valid_yaml, apply=False)
        assert result["proposed_yaml"] is None

    def test_apply_true_generates_yaml(self, valid_yaml):
        result = optimize(content=valid_yaml, apply=True)
        if result["suggestion_count"] > 0:
            assert result["proposed_yaml"] is not None
            assert isinstance(result["proposed_yaml"], str)

    def test_apply_adds_retry_policy(self, valid_yaml):
        result = optimize(content=valid_yaml, apply=True)
        if result["proposed_yaml"]:
            assert "retry_policy" in result["proposed_yaml"]
            assert "max_retries" in result["proposed_yaml"]

    def test_apply_adds_timeout(self, valid_yaml):
        result = optimize(content=valid_yaml, apply=True)
        if result["proposed_yaml"]:
            assert "timeout_sec" in result["proposed_yaml"]


class TestFindSequentialChains:
    """Tests for the _find_sequential_chains helper."""

    def test_finds_chain(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [
            {"from": "a", "to": "b", "mode": "sequential"},
            {"from": "b", "to": "c", "mode": "sequential"},
        ]
        chains = _find_sequential_chains(nodes, edges)
        assert len(chains) == 1
        assert chains[0] == ["a", "b", "c"]

    def test_ignores_non_sequential(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [
            {"from": "a", "to": "b", "mode": "parallel"},
            {"from": "b", "to": "c", "mode": "sequential"},
        ]
        chains = _find_sequential_chains(nodes, edges)
        # Only b->c is sequential, which is length 2 (less than 3)
        assert len(chains) == 0

    def test_empty_edges(self):
        nodes = [{"id": "a"}]
        chains = _find_sequential_chains(nodes, [])
        assert chains == []

    def test_default_mode_is_sequential(self):
        """Edges without explicit mode default to sequential."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [
            {"from": "a", "to": "b"},  # no mode -> defaults to sequential
            {"from": "b", "to": "c"},
        ]
        chains = _find_sequential_chains(nodes, edges)
        assert len(chains) == 1


class TestCheckIndependence:
    """Tests for the _check_independence helper."""

    def test_independent_nodes(self):
        node_map = {
            "a": {"id": "a", "type": "api"},
            "b": {"id": "b", "type": "api"},
            "c": {"id": "c", "type": "api"},
        }
        assert _check_independence(["a", "b", "c"], node_map) is True

    def test_dependent_nodes(self):
        node_map = {
            "a": {"id": "a", "outputs": [{"name": "result"}]},
            "b": {"id": "b", "inputs": [{"name": "result"}]},
            "c": {"id": "c", "type": "api"},
        }
        assert _check_independence(["a", "b", "c"], node_map) is False

    def test_missing_node_in_map(self):
        node_map = {"a": {"id": "a"}}
        # Missing "b" in map should not crash
        assert _check_independence(["a", "b"], node_map) is True
