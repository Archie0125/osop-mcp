"""Tests for tools/risk_assess.py — Security risk assessment."""

from __future__ import annotations

import textwrap

import pytest

from tools.risk_assess import risk_assess, NODE_TYPE_WEIGHT, RISK_LEVEL_SCORE


class TestRiskAssessSimpleWorkflow:
    """Tests for risk assessment on simple/safe workflows."""

    def test_simple_workflow_returns_result(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert isinstance(result, dict)

    def test_simple_workflow_has_score(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert "overall_score" in result
        assert isinstance(result["overall_score"], int)
        assert 0 <= result["overall_score"] <= 100

    def test_simple_workflow_has_verdict(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert result["verdict"] in ("safe", "caution", "warning", "danger")

    def test_simple_workflow_total_nodes(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert result["total_nodes"] == 2

    def test_simple_workflow_no_high_risk_nodes(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert result["high_risk_nodes"] == 0

    def test_result_has_all_expected_keys(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        expected_keys = [
            "overall_score", "verdict", "total_nodes", "high_risk_nodes",
            "total_findings", "by_severity", "has_approval_gates",
            "permissions_required", "secrets_required", "estimated_cost",
            "findings", "node_scores",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"


class TestRiskAssessHighRiskNodes:
    """Tests for workflows with high-risk nodes."""

    def test_high_risk_node_detected(self, high_risk_yaml):
        result = risk_assess(content=high_risk_yaml)
        assert result["high_risk_nodes"] >= 1

    def test_high_risk_without_approval_produces_finding(self, high_risk_yaml):
        result = risk_assess(content=high_risk_yaml)
        risk_001 = [f for f in result["findings"] if f["rule_id"] == "RISK-001"]
        assert len(risk_001) >= 1
        assert risk_001[0]["severity"] in ("high", "critical")

    def test_broad_permissions_detected(self, high_risk_yaml):
        result = risk_assess(content=high_risk_yaml)
        risk_002 = [f for f in result["findings"] if f["rule_id"] == "RISK-002"]
        assert len(risk_002) >= 1
        assert "write:*" in result["permissions_required"]

    def test_destructive_command_detected(self):
        """Destructive commands with low risk_level trigger RISK-003."""
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "destructive"
            name: "Destructive"
            nodes:
              - id: "danger"
                type: "cli"
                name: "Danger Zone"
                security:
                  risk_level: "low"
                runtime:
                  command: "rm -rf /tmp/data"
            edges: []
        """)
        result = risk_assess(content=yaml_str)
        risk_003 = [f for f in result["findings"] if f["rule_id"] == "RISK-003"]
        assert len(risk_003) >= 1

    def test_destructive_high_risk_no_003(self, high_risk_yaml):
        """RISK-003 should NOT fire if risk_level is already high/critical."""
        result = risk_assess(content=high_risk_yaml)
        risk_003 = [f for f in result["findings"] if f["rule_id"] == "RISK-003"]
        # The deploy node has risk_level: high, so RISK-003 should not appear for it
        deploy_003 = [f for f in risk_003 if f.get("node_id") == "deploy"]
        assert len(deploy_003) == 0

    def test_no_error_handling_finding(self, high_risk_yaml):
        """High-risk nodes without fallback/retry trigger RISK-007."""
        result = risk_assess(content=high_risk_yaml)
        risk_007 = [f for f in result["findings"] if f["rule_id"] == "RISK-007"]
        assert len(risk_007) >= 1

    def test_missing_timeout_finding(self, high_risk_yaml):
        """External nodes without timeout_sec trigger RISK-008."""
        result = risk_assess(content=high_risk_yaml)
        risk_008 = [f for f in result["findings"] if f["rule_id"] == "RISK-008"]
        assert len(risk_008) >= 1

    def test_various_destructive_patterns(self):
        """Test multiple destructive command patterns are detected."""
        patterns = [
            ("drop table users", "DROP TABLE"),
            ("kubectl delete pods", "kubectl delete"),
            ("terraform destroy", "terraform destroy"),
            ("git push --force", "git push --force"),
            ("git reset --hard HEAD~1", "git reset --hard"),
        ]
        for cmd, label in patterns:
            yaml_str = textwrap.dedent(f"""\
                osop_version: "1.0"
                id: "test-{label.replace(' ', '-')}"
                name: "Test"
                nodes:
                  - id: "x"
                    type: "cli"
                    name: "X"
                    security:
                      risk_level: "low"
                    runtime:
                      command: "{cmd}"
                edges: []
            """)
            result = risk_assess(content=yaml_str)
            risk_003 = [f for f in result["findings"] if f["rule_id"] == "RISK-003"]
            assert len(risk_003) >= 1, f"RISK-003 not triggered for: {label}"


class TestRiskAssessApprovalGates:
    """Tests for approval gate detection."""

    def test_approval_gate_detected(self, approval_gate_yaml):
        result = risk_assess(content=approval_gate_yaml)
        assert result["has_approval_gates"] is True

    def test_no_approval_gates_in_simple_workflow(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert result["has_approval_gates"] is False

    def test_approval_gate_suppresses_risk_001(self, approval_gate_yaml):
        """When a predecessor has an approval gate, RISK-001 should not fire."""
        result = risk_assess(content=approval_gate_yaml)
        risk_001 = [f for f in result["findings"] if f["rule_id"] == "RISK-001"]
        # deploy node has risk_level: high but review node (predecessor) has approval_gate
        deploy_001 = [f for f in risk_001 if f.get("node_id") == "deploy"]
        assert len(deploy_001) == 0


class TestRiskAssessScoring:
    """Tests for the risk scoring mechanism."""

    def test_safe_workflow_low_score(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "safe"
            name: "Safe"
            nodes:
              - id: "a"
                type: "human"
                name: "Input"
              - id: "b"
                type: "human"
                name: "Review"
            edges:
              - from: "a"
                to: "b"
                mode: "sequential"
        """)
        result = risk_assess(content=yaml_str)
        # Two human nodes (low weight) should score low
        assert result["overall_score"] <= 45
        assert result["verdict"] in ("safe", "caution")

    def test_high_risk_workflow_higher_score(self, high_risk_yaml):
        result = risk_assess(content=high_risk_yaml)
        assert result["overall_score"] > 0

    def test_node_scores_populated(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert len(result["node_scores"]) == 2
        for ns in result["node_scores"]:
            assert "node_id" in ns
            assert "base_score" in ns
            assert "mitigated_score" in ns

    def test_by_severity_counts(self, high_risk_yaml):
        result = risk_assess(content=high_risk_yaml)
        by_sev = result["by_severity"]
        assert isinstance(by_sev, dict)
        total = sum(by_sev.values())
        assert total == result["total_findings"]


class TestRiskAssessCostExposure:
    """Tests for cost exposure detection."""

    def test_unbounded_cost_exposure(self):
        """More than 2 agent nodes without cost triggers RISK-005."""
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "costly"
            name: "Costly"
            nodes:
              - id: "a1"
                type: "agent"
                name: "Agent 1"
              - id: "a2"
                type: "agent"
                name: "Agent 2"
              - id: "a3"
                type: "agent"
                name: "Agent 3"
            edges:
              - from: "a1"
                to: "a2"
                mode: "sequential"
              - from: "a2"
                to: "a3"
                mode: "sequential"
        """)
        result = risk_assess(content=yaml_str)
        risk_005 = [f for f in result["findings"] if f["rule_id"] == "RISK-005"]
        assert len(risk_005) >= 1

    def test_estimated_cost_aggregation(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "costed"
            name: "Costed"
            nodes:
              - id: "a"
                type: "agent"
                name: "Agent"
                cost:
                  estimated: 0.50
              - id: "b"
                type: "agent"
                name: "Agent 2"
                cost:
                  estimated: 1.25
            edges:
              - from: "a"
                to: "b"
                mode: "sequential"
        """)
        result = risk_assess(content=yaml_str)
        assert result["estimated_cost"] == 1.75

    def test_no_cost_returns_none(self, valid_yaml):
        result = risk_assess(content=valid_yaml)
        assert result["estimated_cost"] is None


class TestRiskAssessSecrets:
    """Tests for secrets detection."""

    def test_secrets_collected(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "secrets"
            name: "Secrets"
            nodes:
              - id: "a"
                type: "api"
                name: "API Call"
                security:
                  secrets:
                    - "API_KEY"
                    - "DB_PASSWORD"
            edges: []
        """)
        result = risk_assess(content=yaml_str)
        assert "API_KEY" in result["secrets_required"]
        assert "DB_PASSWORD" in result["secrets_required"]


class TestRiskAssessConstants:
    """Tests for module-level constants."""

    def test_node_type_weight_has_common_types(self):
        assert "cli" in NODE_TYPE_WEIGHT
        assert "api" in NODE_TYPE_WEIGHT
        assert "agent" in NODE_TYPE_WEIGHT
        assert "human" in NODE_TYPE_WEIGHT

    def test_risk_level_score_ordering(self):
        assert RISK_LEVEL_SCORE["low"] < RISK_LEVEL_SCORE["medium"]
        assert RISK_LEVEL_SCORE["medium"] < RISK_LEVEL_SCORE["high"]
        assert RISK_LEVEL_SCORE["high"] < RISK_LEVEL_SCORE["critical"]
