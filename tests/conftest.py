"""Shared fixtures for OSOP MCP Server tests."""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `tools.*` imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# YAML fixture strings
# ---------------------------------------------------------------------------

VALID_WORKFLOW_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "test-workflow"
    name: "Test Workflow"
    description: "A minimal valid workflow for testing."
    nodes:
      - id: "step_a"
        type: "cli"
        name: "Step A"
        description: "First step."
      - id: "step_b"
        type: "api"
        name: "Step B"
        description: "Second step."
    edges:
      - from: "step_a"
        to: "step_b"
        mode: "sequential"
""")

VALID_WORKFLOW_THREE_NODES_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "three-step"
    name: "Three Step Workflow"
    description: "Workflow with three sequential steps."
    nodes:
      - id: "a"
        type: "cli"
        name: "Step A"
      - id: "b"
        type: "api"
        name: "Step B"
      - id: "c"
        type: "agent"
        name: "Step C"
    edges:
      - from: "a"
        to: "b"
        mode: "sequential"
      - from: "b"
        to: "c"
        mode: "sequential"
""")

HIGH_RISK_WORKFLOW_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "high-risk"
    name: "High Risk Workflow"
    description: "Workflow with risky operations."
    nodes:
      - id: "deploy"
        type: "cli"
        name: "Deploy to Prod"
        security:
          risk_level: "high"
          permissions:
            - "write:*"
        runtime:
          command: "rm -rf /tmp/old && terraform destroy"
      - id: "notify"
        type: "api"
        name: "Notify Team"
    edges:
      - from: "deploy"
        to: "notify"
        mode: "sequential"
""")

APPROVAL_GATE_WORKFLOW_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "approval-gate"
    name: "Approval Gate Workflow"
    description: "Workflow with proper approval gates."
    nodes:
      - id: "review"
        type: "human"
        name: "Human Review"
        approval_gate:
          required: true
          approvers:
            - "admin"
      - id: "deploy"
        type: "cli"
        name: "Deploy to Prod"
        security:
          risk_level: "high"
    edges:
      - from: "review"
        to: "deploy"
        mode: "sequential"
""")

WORKFLOW_WITH_ORPHAN_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "orphan-test"
    name: "Orphan Node Workflow"
    description: "Workflow with an orphan node."
    nodes:
      - id: "connected_a"
        type: "cli"
        name: "Connected A"
      - id: "connected_b"
        type: "api"
        name: "Connected B"
      - id: "orphan_node"
        type: "agent"
        name: "Orphan Node"
    edges:
      - from: "connected_a"
        to: "connected_b"
        mode: "sequential"
""")

WORKFLOW_BAD_EDGE_REF_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "bad-edge-ref"
    name: "Bad Edge Ref"
    description: "Edge references non-existent node."
    nodes:
      - id: "real_node"
        type: "cli"
        name: "Real Node"
    edges:
      - from: "real_node"
        to: "ghost_node"
        mode: "sequential"
""")

WORKFLOW_WITH_TESTS_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "workflow-with-tests"
    name: "Testable Workflow"
    description: "Has test cases."
    nodes:
      - id: "step_a"
        type: "cli"
        name: "Step A"
    edges: []
    tests:
      - name: "test_basic"
        description: "A basic test."
      - name: "test_advanced"
        description: "An advanced test."
""")

PARALLEL_CANDIDATE_YAML = textwrap.dedent("""\
    osop_version: "1.0"
    id: "parallel-candidate"
    name: "Parallel Candidate"
    description: "Three independent sequential nodes that could be parallelized."
    nodes:
      - id: "a"
        type: "api"
        name: "Fetch Users"
      - id: "b"
        type: "api"
        name: "Fetch Orders"
      - id: "c"
        type: "api"
        name: "Fetch Products"
    edges:
      - from: "a"
        to: "b"
        mode: "sequential"
      - from: "b"
        to: "c"
        mode: "sequential"
""")

RUN_HISTORY_JSON = textwrap.dedent("""\
    [
      {
        "node_records": [
          {"node_id": "a", "status": "COMPLETED", "duration_ms": 8000},
          {"node_id": "b", "status": "FAILED", "duration_ms": 200, "error": {"message": "timeout"}},
          {"node_id": "c", "status": "COMPLETED", "duration_ms": 100}
        ]
      },
      {
        "node_records": [
          {"node_id": "a", "status": "COMPLETED", "duration_ms": 7500},
          {"node_id": "b", "status": "FAILED", "duration_ms": 150, "error": {"message": "timeout"}},
          {"node_id": "c", "status": "COMPLETED", "duration_ms": 120}
        ]
      }
    ]
""")


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_yaml():
    return VALID_WORKFLOW_YAML


@pytest.fixture
def valid_three_nodes_yaml():
    return VALID_WORKFLOW_THREE_NODES_YAML


@pytest.fixture
def high_risk_yaml():
    return HIGH_RISK_WORKFLOW_YAML


@pytest.fixture
def approval_gate_yaml():
    return APPROVAL_GATE_WORKFLOW_YAML


@pytest.fixture
def orphan_yaml():
    return WORKFLOW_WITH_ORPHAN_YAML


@pytest.fixture
def bad_edge_ref_yaml():
    return WORKFLOW_BAD_EDGE_REF_YAML


@pytest.fixture
def workflow_with_tests_yaml():
    return WORKFLOW_WITH_TESTS_YAML


@pytest.fixture
def parallel_candidate_yaml():
    return PARALLEL_CANDIDATE_YAML


@pytest.fixture
def run_history_json():
    return RUN_HISTORY_JSON


@pytest.fixture
def valid_yaml_file(tmp_path, valid_yaml):
    """Write a valid YAML to a temp file and return the path."""
    p = tmp_path / "valid.osop.yaml"
    p.write_text(valid_yaml, encoding="utf-8")
    return str(p)
