"""Tests for OSOP format converters (import/export)."""

from __future__ import annotations

import json

import pytest
import yaml

from tools.convert import (
    convert,
    import_crewai,
    import_n8n,
    import_github_actions,
    import_airflow,
    import_argo,
    import_langgraph,
    export_crewai,
    export_n8n,
    export_argo,
)


# --- Fixtures ---

CREWAI_AGENTS = """
researcher:
  role: Research Analyst
  goal: Conduct thorough research on given topics
  backstory: You are an experienced researcher with 10 years of experience.
  tools: [web_search, arxiv_search]
  llm: gpt-4

writer:
  role: Content Writer
  goal: Write compelling articles based on research
  backstory: You are a skilled technical writer.
"""

CREWAI_TASKS = """
research_task:
  description: Research the topic thoroughly
  expected_output: Comprehensive research report
  agent: researcher

writing_task:
  description: Write an article based on research findings
  expected_output: Well-written article
  agent: writer
"""

N8N_WORKFLOW = json.dumps({
    "name": "API Data Pipeline",
    "nodes": [
        {"name": "Start", "type": "n8n-nodes-base.manualTrigger", "position": [250, 300], "parameters": {}},
        {"name": "Fetch Data", "type": "n8n-nodes-base.httpRequest", "position": [450, 300], "parameters": {"url": "https://api.example.com/data", "method": "GET"}},
        {"name": "Transform", "type": "n8n-nodes-base.code", "position": [650, 300], "parameters": {}},
        {"name": "Save to DB", "type": "n8n-nodes-base.postgres", "position": [850, 300], "parameters": {}},
    ],
    "connections": {
        "Start": {"main": [[{"node": "Fetch Data", "type": "main", "index": 0}]]},
        "Fetch Data": {"main": [[{"node": "Transform", "type": "main", "index": 0}]]},
        "Transform": {"main": [[{"node": "Save to DB", "type": "main", "index": 0}]]},
    },
})

GHA_WORKFLOW = """
name: CI/CD Pipeline
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: npm test
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint code
        run: npm run lint
  deploy:
    needs: [test, lint]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: npm run deploy
"""

AIRFLOW_DAG = '''
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from datetime import datetime

with DAG("etl_pipeline", start_date=datetime(2024, 1, 1)) as dag:
    extract = BashOperator(task_id="extract", bash_command="python extract.py")
    transform = PythonOperator(task_id="transform", python_callable=transform_data)
    load = BashOperator(task_id="load", bash_command="python load.py")

    extract >> transform >> load
'''

ARGO_WORKFLOW = """
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: ci-pipeline
spec:
  entrypoint: main
  templates:
    - name: main
      dag:
        tasks:
          - name: build
            template: build-tmpl
          - name: test
            template: test-tmpl
            dependencies: [build]
          - name: deploy
            template: deploy-tmpl
            dependencies: [test]
            when: "{{tasks.test.outputs.result}} == passed"
    - name: build-tmpl
      container:
        image: node:18
        command: [npm, run, build]
    - name: test-tmpl
      script:
        image: node:18
        command: [node]
        source: "console.log('tests')"
    - name: deploy-tmpl
      container:
        image: kubectl:latest
        command: [kubectl, apply]
"""

LANGGRAPH_CODE = '''
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    messages: list
    next: str

graph = StateGraph(AgentState)
graph.add_node("researcher", research_node)
graph.add_node("writer", write_node)
graph.add_node("reviewer", review_node)
graph.add_edge("researcher", "writer")
graph.add_edge("writer", "reviewer")
graph.add_conditional_edges("reviewer", should_continue, {"continue": "writer", "end": END})
graph.set_entry_point("researcher")
'''


# --- CrewAI Tests ---

class TestCrewAIImport:
    def test_basic_import(self):
        result = import_crewai(CREWAI_AGENTS, tasks_yaml=CREWAI_TASKS)
        data = yaml.safe_load(result)
        assert data["osop_version"] == "1.0"
        assert len(data["nodes"]) == 2
        assert data["nodes"][0]["type"] == "agent"
        assert len(data["edges"]) == 1

    def test_agent_properties(self):
        result = import_crewai(CREWAI_AGENTS, tasks_yaml=CREWAI_TASKS)
        data = yaml.safe_load(result)
        researcher = next(n for n in data["nodes"] if n["id"] == "researcher")
        assert researcher["purpose"] == "Conduct thorough research on given topics"
        assert researcher["runtime"]["config"]["system_prompt"] == "You are an experienced researcher with 10 years of experience."
        assert researcher["runtime"]["config"]["tools"] == ["web_search", "arxiv_search"]

    def test_edge_order(self):
        result = import_crewai(CREWAI_AGENTS, tasks_yaml=CREWAI_TASKS)
        data = yaml.safe_load(result)
        assert data["edges"][0]["from"] == "researcher"
        assert data["edges"][0]["to"] == "writer"
        assert data["edges"][0]["mode"] == "sequential"

    def test_single_agent(self):
        single = "worker:\n  role: Worker\n  goal: Do work\n"
        result = import_crewai(single)
        data = yaml.safe_load(result)
        assert len(data["nodes"]) == 1
        assert len(data["edges"]) == 0


class TestCrewAIExport:
    def test_round_trip(self):
        osop_result = import_crewai(CREWAI_AGENTS, tasks_yaml=CREWAI_TASKS)
        exported = export_crewai(osop_result)
        assert "agents.yaml" in exported
        assert "tasks.yaml" in exported
        agents = yaml.safe_load(exported["agents.yaml"])
        tasks = yaml.safe_load(exported["tasks.yaml"])
        assert len(agents) == 2
        assert len(tasks) >= 1


# --- n8n Tests ---

class TestN8nImport:
    def test_basic_import(self):
        result = import_n8n(N8N_WORKFLOW)
        data = yaml.safe_load(result)
        assert data["osop_version"] == "1.0"
        assert data["name"] == "API Data Pipeline"
        assert len(data["nodes"]) == 4
        assert len(data["edges"]) == 3

    def test_node_types(self):
        result = import_n8n(N8N_WORKFLOW)
        data = yaml.safe_load(result)
        type_map = {n["id"]: n["type"] for n in data["nodes"]}
        assert type_map["fetch-data"] == "api"
        assert type_map["transform"] == "cli"
        assert type_map["save-to-db"] == "db"

    def test_edges(self):
        result = import_n8n(N8N_WORKFLOW)
        data = yaml.safe_load(result)
        edge_pairs = [(e["from"], e["to"]) for e in data["edges"]]
        assert ("start", "fetch-data") in edge_pairs
        assert ("fetch-data", "transform") in edge_pairs
        assert ("transform", "save-to-db") in edge_pairs


class TestN8nExport:
    def test_round_trip(self):
        osop_result = import_n8n(N8N_WORKFLOW)
        exported = export_n8n(osop_result)
        n8n_data = json.loads(exported)
        assert "nodes" in n8n_data
        assert "connections" in n8n_data
        assert len(n8n_data["nodes"]) == 4


# --- GitHub Actions Tests ---

class TestGitHubActionsImport:
    def test_basic_import(self):
        result = import_github_actions(GHA_WORKFLOW)
        data = yaml.safe_load(result)
        assert data["osop_version"] == "1.0"
        assert len(data["nodes"]) == 3
        node_ids = {n["id"] for n in data["nodes"]}
        assert "test" in node_ids
        assert "lint" in node_ids
        assert "deploy" in node_ids

    def test_dependencies(self):
        result = import_github_actions(GHA_WORKFLOW)
        data = yaml.safe_load(result)
        deploy_edges = [e for e in data["edges"] if e["to"] == "deploy"]
        assert len(deploy_edges) == 2
        from_nodes = {e["from"] for e in deploy_edges}
        assert "test" in from_nodes
        assert "lint" in from_nodes

    def test_conditional_edge(self):
        result = import_github_actions(GHA_WORKFLOW)
        data = yaml.safe_load(result)
        cond_edges = [e for e in data["edges"] if e.get("mode") == "conditional"]
        assert len(cond_edges) >= 1
        assert "refs/heads/main" in cond_edges[0]["condition"]


# --- Airflow Tests ---

class TestAirflowImport:
    def test_basic_import(self):
        result = import_airflow(AIRFLOW_DAG)
        data = yaml.safe_load(result)
        assert data["osop_version"] == "1.0"
        assert len(data["nodes"]) == 3

    def test_node_types(self):
        result = import_airflow(AIRFLOW_DAG)
        data = yaml.safe_load(result)
        type_map = {n["id"]: n["type"] for n in data["nodes"]}
        assert type_map["extract"] == "cli"
        assert type_map["transform"] == "agent"
        assert type_map["load"] == "cli"

    def test_edge_chain(self):
        result = import_airflow(AIRFLOW_DAG)
        data = yaml.safe_load(result)
        edge_pairs = [(e["from"], e["to"]) for e in data["edges"]]
        assert ("extract", "transform") in edge_pairs
        assert ("transform", "load") in edge_pairs


# --- Argo Tests ---

class TestArgoImport:
    def test_basic_import(self):
        result = import_argo(ARGO_WORKFLOW)
        data = yaml.safe_load(result)
        assert data["osop_version"] == "1.0"
        assert len(data["nodes"]) == 3

    def test_dependencies(self):
        result = import_argo(ARGO_WORKFLOW)
        data = yaml.safe_load(result)
        test_edge = next(e for e in data["edges"] if e["to"] == "test")
        assert test_edge["from"] == "build"
        assert test_edge["mode"] == "sequential"

    def test_conditional(self):
        result = import_argo(ARGO_WORKFLOW)
        data = yaml.safe_load(result)
        deploy_edge = next(e for e in data["edges"] if e["to"] == "deploy")
        assert deploy_edge["mode"] == "conditional"
        assert "passed" in deploy_edge["condition"]

    def test_node_types(self):
        result = import_argo(ARGO_WORKFLOW)
        data = yaml.safe_load(result)
        type_map = {n["id"]: n["type"] for n in data["nodes"]}
        assert type_map["build"] == "docker"
        assert type_map["test"] == "cli"
        assert type_map["deploy"] == "docker"


class TestArgoExport:
    def test_round_trip(self):
        osop_result = import_argo(ARGO_WORKFLOW)
        exported = export_argo(osop_result)
        argo_data = yaml.safe_load(exported)
        assert argo_data["apiVersion"] == "argoproj.io/v1alpha1"
        assert argo_data["kind"] == "Workflow"
        assert "templates" in argo_data["spec"]


# --- LangGraph Tests ---

class TestLangGraphImport:
    def test_basic_import(self):
        result = import_langgraph(LANGGRAPH_CODE)
        data = yaml.safe_load(result)
        assert data["osop_version"] == "1.0"
        assert len(data["nodes"]) == 3

    def test_all_nodes_are_agents(self):
        result = import_langgraph(LANGGRAPH_CODE)
        data = yaml.safe_load(result)
        for node in data["nodes"]:
            assert node["type"] == "agent"

    def test_edges(self):
        result = import_langgraph(LANGGRAPH_CODE)
        data = yaml.safe_load(result)
        seq_edges = [e for e in data["edges"] if e["mode"] == "sequential"]
        cond_edges = [e for e in data["edges"] if e["mode"] == "conditional"]
        assert len(seq_edges) >= 2
        assert len(cond_edges) >= 1

    def test_conditional_edge(self):
        result = import_langgraph(LANGGRAPH_CODE)
        data = yaml.safe_load(result)
        cond = [e for e in data["edges"] if e["mode"] == "conditional"]
        assert any(e["from"] == "reviewer" and e["to"] == "writer" for e in cond)


# --- Unified convert() Tests ---

class TestConvertDispatch:
    def test_import_crewai(self):
        result = convert(content=CREWAI_AGENTS, source_format="crewai")
        assert "error" not in result
        assert result["format"] == "osop"

    def test_import_n8n(self):
        result = convert(content=N8N_WORKFLOW, source_format="n8n")
        assert "error" not in result

    def test_export_n8n(self):
        osop = import_n8n(N8N_WORKFLOW)
        result = convert(content=osop, target_format="n8n")
        assert "error" not in result

    def test_unsupported_format(self):
        result = convert(content="test", source_format="unknown-format")
        assert "error" in result

    def test_no_format_specified(self):
        result = convert(content="test")
        assert "error" in result


# --- Diff Tests ---

class TestDiff:
    def test_identical(self):
        from tools.diff import diff_workflows
        osop = import_n8n(N8N_WORKFLOW)
        result = diff_workflows(content_a=osop, content_b=osop)
        assert result["identical"] is True
        assert result["total_changes"] == 0

    def test_different(self):
        from tools.diff import diff_workflows
        osop_a = import_n8n(N8N_WORKFLOW)
        osop_b = import_github_actions(GHA_WORKFLOW)
        result = diff_workflows(content_a=osop_a, content_b=osop_b)
        assert result["identical"] is False
        assert result["total_changes"] > 0
