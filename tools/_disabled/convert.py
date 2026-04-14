"""OSOP format converter — import/export between OSOP and external workflow formats.

Supports: CrewAI, n8n, GitHub Actions, Airflow, Argo Workflows, LangGraph.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml


# ---------- helpers ----------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _node_type_for_n8n(n8n_type: str) -> str:
    """Map n8n node type to OSOP node type."""
    t = n8n_type.lower()
    if "httprequest" in t or "webhook" in t:
        return "api"
    if "code" in t or "executecommand" in t or "ssh" in t:
        return "cli"
    if "if" in t or "switch" in t or "filter" in t:
        return "system"
    if "postgres" in t or "mysql" in t or "mongo" in t or "redis" in t:
        return "db"
    if "slack" in t or "email" in t or "discord" in t or "telegram" in t:
        return "api"
    if "git" in t or "github" in t or "gitlab" in t:
        return "git"
    if "docker" in t:
        return "docker"
    if "s3" in t or "gcs" in t or "aws" in t or "azure" in t:
        return "infra"
    if "openai" in t or "anthropic" in t or "llm" in t or "ai" in t:
        return "agent"
    if "cron" in t or "schedule" in t or "interval" in t:
        return "system"
    if "manual" in t or "form" in t:
        return "human"
    if "merge" in t or "set" in t or "splitinbatches" in t:
        return "data"
    return "system"


def _airflow_op_to_type(class_name: str) -> str:
    """Map Airflow operator class name to OSOP node type."""
    c = class_name.lower()
    if "bash" in c:
        return "cli"
    if "python" in c or "branch" in c:
        return "agent"
    if "http" in c or "simplehttp" in c:
        return "api"
    if "docker" in c:
        return "docker"
    if "trigger" in c:
        return "system"
    if "email" in c or "slack" in c:
        return "api"
    if "postgres" in c or "mysql" in c or "sql" in c:
        return "db"
    if "s3" in c or "gcs" in c:
        return "infra"
    return "system"


def _argo_template_to_type(template: dict) -> str:
    """Map Argo template spec to OSOP node type."""
    if "container" in template:
        return "docker"
    if "script" in template:
        return "cli"
    if "resource" in template:
        return "infra"
    if "suspend" in template:
        return "human"
    if "dag" in template or "steps" in template:
        return "system"
    return "system"


# ---------- IMPORTERS ----------

def import_crewai(source: str, tasks_yaml: str | None = None, **kwargs: Any) -> str:
    """Import CrewAI agents.yaml + tasks.yaml → OSOP YAML.

    Args:
        source: agents.yaml content (or combined YAML with both agents and tasks sections)
        tasks_yaml: optional separate tasks.yaml content
    """
    agents_data = yaml.safe_load(source) or {}
    tasks_data: dict = {}

    if tasks_yaml:
        tasks_data = yaml.safe_load(tasks_yaml) or {}
    elif "tasks" in agents_data and isinstance(agents_data.get("tasks"), dict):
        tasks_data = agents_data.pop("tasks")

    # Build nodes from agents
    nodes: list[dict] = []
    agent_ids: list[str] = []
    for agent_id, agent_def in agents_data.items():
        if not isinstance(agent_def, dict):
            continue
        node: dict[str, Any] = {
            "id": _slugify(agent_id),
            "type": "agent",
            "name": agent_def.get("role", agent_id),
            "purpose": agent_def.get("goal", ""),
        }
        runtime_config: dict[str, Any] = {}
        if agent_def.get("backstory"):
            runtime_config["system_prompt"] = agent_def["backstory"]
        if agent_def.get("tools"):
            runtime_config["tools"] = agent_def["tools"]
        if agent_def.get("llm"):
            node["runtime"] = {"model": agent_def["llm"]}
        if runtime_config:
            node.setdefault("runtime", {})["config"] = runtime_config
        if agent_def.get("allow_delegation"):
            node["subtype"] = "coordinator"
        else:
            node["subtype"] = "worker"
        nodes.append(node)
        agent_ids.append(_slugify(agent_id))

    # Build edges from tasks (task order → sequential edges)
    edges: list[dict] = []
    task_sequence: list[str] = []
    for task_id, task_def in tasks_data.items():
        if not isinstance(task_def, dict):
            continue
        agent_ref = _slugify(task_def.get("agent", ""))
        if agent_ref in agent_ids:
            task_sequence.append(agent_ref)

    seen: set[tuple[str, str]] = set()
    for i in range(len(task_sequence) - 1):
        pair = (task_sequence[i], task_sequence[i + 1])
        if pair not in seen and pair[0] != pair[1]:
            edges.append({"from": pair[0], "to": pair[1], "mode": "sequential"})
            seen.add(pair)

    workflow = {
        "osop_version": "1.0",
        "id": _slugify(kwargs.get("name", "crewai-workflow")),
        "name": kwargs.get("name", "CrewAI Workflow"),
        "description": f"Imported from CrewAI — {len(nodes)} agents, {len(edges)} task edges.",
        "nodes": nodes,
        "edges": edges,
    }
    return yaml.dump(workflow, default_flow_style=False, sort_keys=False, allow_unicode=True)


def import_n8n(source: str, **kwargs: Any) -> str:
    """Import n8n workflow JSON → OSOP YAML."""
    data = json.loads(source)
    wf_name = data.get("name", "n8n Workflow")

    nodes: list[dict] = []
    n8n_nodes = data.get("nodes", [])
    for n8n_node in n8n_nodes:
        node_name = n8n_node.get("name", "")
        n8n_type = n8n_node.get("type", "")
        node_id = _slugify(node_name) or f"node-{len(nodes)}"
        osop_type = _node_type_for_n8n(n8n_type)

        node: dict[str, Any] = {
            "id": node_id,
            "type": osop_type,
            "name": node_name,
            "description": f"n8n node: {n8n_type}",
        }

        params = n8n_node.get("parameters", {})
        if params.get("url"):
            node["runtime"] = {"endpoint": params["url"], "method": params.get("method", "GET")}

        nodes.append(node)

    # Build edges from connections
    edges: list[dict] = []
    connections = data.get("connections", {})
    for from_name, conn_data in connections.items():
        from_id = _slugify(from_name)
        main_conns = conn_data.get("main", [])
        for output_group in main_conns:
            if isinstance(output_group, list):
                for conn in output_group:
                    to_name = conn.get("node", "")
                    to_id = _slugify(to_name)
                    if from_id and to_id:
                        edges.append({"from": from_id, "to": to_id, "mode": "sequential"})

    workflow = {
        "osop_version": "1.0",
        "id": _slugify(wf_name),
        "name": wf_name,
        "description": f"Imported from n8n — {len(nodes)} nodes.",
        "nodes": nodes,
        "edges": edges,
    }
    return yaml.dump(workflow, default_flow_style=False, sort_keys=False, allow_unicode=True)


def import_github_actions(source: str, **kwargs: Any) -> str:
    """Import GitHub Actions workflow YAML → OSOP YAML."""
    data = yaml.safe_load(source) or {}
    wf_name = data.get("name", "GitHub Actions Workflow")

    nodes: list[dict] = []
    edges: list[dict] = []
    jobs = data.get("jobs", {})

    for job_id, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        # Determine node type
        node_type = "cicd"
        if job_def.get("environment") and isinstance(job_def["environment"], dict) and job_def["environment"].get("required_reviewers"):
            node_type = "human"
        steps = job_def.get("steps", [])
        docker_steps = [s for s in steps if isinstance(s, dict) and "docker" in str(s.get("uses", "")).lower()]
        if docker_steps:
            node_type = "docker"

        step_descriptions = []
        for s in steps:
            if isinstance(s, dict):
                if s.get("name"):
                    step_descriptions.append(s["name"])
                elif s.get("run"):
                    step_descriptions.append(f"run: {s['run'][:80]}")
                elif s.get("uses"):
                    step_descriptions.append(f"uses: {s['uses']}")

        node: dict[str, Any] = {
            "id": _slugify(job_id),
            "type": node_type,
            "name": job_def.get("name", job_id),
            "description": "; ".join(step_descriptions[:5]) if step_descriptions else f"Job: {job_id}",
        }
        if job_def.get("runs-on"):
            node.setdefault("runtime", {})["config"] = {"runs_on": job_def["runs-on"]}
        nodes.append(node)

        # Build edges from needs
        needs = job_def.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        for dep in needs:
            edge: dict[str, Any] = {"from": _slugify(dep), "to": _slugify(job_id)}
            if job_def.get("if"):
                edge["mode"] = "conditional"
                edge["condition"] = str(job_def["if"])
            else:
                edge["mode"] = "sequential"
            edges.append(edge)

    # Trigger description
    on_trigger = data.get("on", data.get(True, ""))  # YAML parses `on:` as True key sometimes
    trigger_desc = ""
    if on_trigger:
        trigger_desc = f" Triggers: {json.dumps(on_trigger) if isinstance(on_trigger, (dict, list)) else str(on_trigger)}."

    workflow = {
        "osop_version": "1.0",
        "id": _slugify(wf_name),
        "name": wf_name,
        "description": f"Imported from GitHub Actions — {len(nodes)} jobs.{trigger_desc}",
        "nodes": nodes,
        "edges": edges,
    }
    return yaml.dump(workflow, default_flow_style=False, sort_keys=False, allow_unicode=True)


def import_airflow(source: str, **kwargs: Any) -> str:
    """Import Airflow DAG Python file → OSOP YAML (best-effort AST parsing)."""
    import ast

    tree = ast.parse(source)
    dag_name = "airflow-dag"
    nodes: list[dict] = []
    edges: list[dict] = []
    task_vars: dict[str, str] = {}  # variable_name → task_id

    for node in ast.walk(tree):
        # Extract DAG name from DAG(...) or @dag
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name == "DAG":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        dag_name = arg.value
                        break
                for kw in node.keywords:
                    if kw.arg == "dag_id" and isinstance(kw.value, ast.Constant):
                        dag_name = str(kw.value.value)

            # Extract operator instantiations
            if func_name and ("operator" in func_name.lower() or "sensor" in func_name.lower()):
                task_id = None
                op_kwargs: dict[str, Any] = {}
                for kw in node.keywords:
                    if kw.arg == "task_id" and isinstance(kw.value, ast.Constant):
                        task_id = str(kw.value.value)
                    elif kw.arg == "bash_command" and isinstance(kw.value, ast.Constant):
                        op_kwargs["command"] = str(kw.value.value)
                    elif kw.arg == "python_callable" and isinstance(kw.value, ast.Name):
                        op_kwargs["callable"] = kw.value.id

                if task_id:
                    osop_type = _airflow_op_to_type(func_name)
                    desc_parts = [f"Airflow {func_name}"]
                    if op_kwargs.get("command"):
                        desc_parts.append(f"cmd: {op_kwargs['command'][:60]}")
                    if op_kwargs.get("callable"):
                        desc_parts.append(f"fn: {op_kwargs['callable']}")

                    nodes.append({
                        "id": _slugify(task_id),
                        "type": osop_type,
                        "name": task_id,
                        "description": "; ".join(desc_parts),
                    })

        # Find assignments like: task_a = SomeOperator(task_id="...")
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                # Try to extract task_id from the call
                for kw in node.value.keywords:
                    if kw.arg == "task_id" and isinstance(kw.value, ast.Constant):
                        task_vars[target.id] = _slugify(str(kw.value.value))

    # Extract >> chains from BinOp with RShift
    def _extract_chain(node: ast.expr) -> list[str]:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
            return _extract_chain(node.left) + _extract_chain(node.right)
        if isinstance(node, ast.Name):
            return [task_vars.get(node.id, _slugify(node.id))]
        if isinstance(node, ast.List):
            result = []
            for elt in node.elts:
                if isinstance(elt, ast.Name):
                    result.append(task_vars.get(elt.id, _slugify(elt.id)))
            return result
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.RShift):
            chain = _extract_chain(node.value)
            node_ids = {n["id"] for n in nodes}
            for i in range(len(chain) - 1):
                from_id, to_id = chain[i], chain[i + 1]
                if from_id in node_ids and to_id in node_ids:
                    edges.append({"from": from_id, "to": to_id, "mode": "sequential"})

    workflow = {
        "osop_version": "1.0",
        "id": _slugify(dag_name),
        "name": dag_name,
        "description": f"Imported from Airflow DAG — {len(nodes)} tasks.",
        "nodes": nodes,
        "edges": edges,
    }
    return yaml.dump(workflow, default_flow_style=False, sort_keys=False, allow_unicode=True)


def import_argo(source: str, **kwargs: Any) -> str:
    """Import Argo Workflows YAML → OSOP YAML."""
    data = yaml.safe_load(source) or {}
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    wf_name = metadata.get("name", spec.get("entrypoint", "argo-workflow"))

    # Build template lookup
    templates = {t["name"]: t for t in spec.get("templates", []) if isinstance(t, dict) and "name" in t}

    nodes: list[dict] = []
    edges: list[dict] = []

    # Find the entrypoint template
    entrypoint = spec.get("entrypoint", "")
    main_template = templates.get(entrypoint, {})

    # Handle DAG-based templates
    dag = main_template.get("dag", {})
    dag_tasks = dag.get("tasks", [])

    for task in dag_tasks:
        if not isinstance(task, dict):
            continue
        task_name = task.get("name", "")
        template_ref = task.get("template", "")
        ref_template = templates.get(template_ref, {})
        osop_type = _argo_template_to_type(ref_template)

        desc_parts = [f"Argo template: {template_ref}"]
        container = ref_template.get("container", {})
        if container.get("image"):
            desc_parts.append(f"image: {container['image']}")
        if container.get("command"):
            desc_parts.append(f"cmd: {' '.join(container['command'][:3])}")
        script = ref_template.get("script", {})
        if script.get("image"):
            desc_parts.append(f"image: {script['image']}")

        nodes.append({
            "id": _slugify(task_name),
            "type": osop_type,
            "name": task_name,
            "description": "; ".join(desc_parts),
        })

        # Dependencies → edges
        deps = task.get("dependencies", [])
        when_cond = task.get("when", "")
        for dep in deps:
            edge: dict[str, Any] = {"from": _slugify(dep), "to": _slugify(task_name)}
            if when_cond:
                edge["mode"] = "conditional"
                edge["condition"] = when_cond
            else:
                edge["mode"] = "sequential"
            edges.append(edge)

    # Handle steps-based templates (list of lists)
    steps_list = main_template.get("steps", [])
    prev_step_ids: list[str] = []
    for step_group in steps_list:
        if not isinstance(step_group, list):
            continue
        current_ids: list[str] = []
        for step in step_group:
            if not isinstance(step, dict):
                continue
            step_name = step.get("name", "")
            template_ref = step.get("template", "")
            ref_template = templates.get(template_ref, {})
            osop_type = _argo_template_to_type(ref_template)

            nodes.append({
                "id": _slugify(step_name),
                "type": osop_type,
                "name": step_name,
                "description": f"Argo step template: {template_ref}",
            })
            current_ids.append(_slugify(step_name))

            for prev_id in prev_step_ids:
                edges.append({"from": prev_id, "to": _slugify(step_name), "mode": "sequential"})
        prev_step_ids = current_ids

    workflow = {
        "osop_version": "1.0",
        "id": _slugify(wf_name),
        "name": wf_name,
        "description": f"Imported from Argo Workflows — {len(nodes)} tasks.",
        "nodes": nodes,
        "edges": edges,
    }
    return yaml.dump(workflow, default_flow_style=False, sort_keys=False, allow_unicode=True)


def import_langgraph(source: str, **kwargs: Any) -> str:
    """Import LangGraph Python code (StateGraph) → OSOP YAML (best-effort AST parsing)."""
    import ast

    tree = ast.parse(source)
    nodes: list[dict] = []
    edges: list[dict] = []
    entry_point: str | None = None
    graph_var: str | None = None

    for node in ast.walk(tree):
        # Find StateGraph instantiation
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                func = node.value.func
                func_name = ""
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr
                if func_name == "StateGraph":
                    pass  # Found the graph variable

        # Find add_node, add_edge, add_conditional_edges, set_entry_point
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                method = call.func.attr

                if method == "add_node" and len(call.args) >= 1:
                    name_arg = call.args[0]
                    if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
                        node_name = name_arg.value
                        func_name = ""
                        if len(call.args) >= 2 and isinstance(call.args[1], ast.Name):
                            func_name = call.args[1].id
                        nodes.append({
                            "id": _slugify(node_name),
                            "type": "agent",
                            "name": node_name,
                            "description": f"LangGraph node{f': {func_name}' if func_name else ''}",
                        })

                elif method == "add_edge" and len(call.args) >= 2:
                    from_arg, to_arg = call.args[0], call.args[1]
                    from_name = ""
                    to_name = ""
                    if isinstance(from_arg, ast.Constant):
                        from_name = str(from_arg.value)
                    if isinstance(to_arg, ast.Constant):
                        to_name = str(to_arg.value)
                    elif isinstance(to_arg, ast.Attribute) and to_arg.attr == "END":
                        to_name = "__end__"
                    elif isinstance(to_arg, ast.Name) and to_arg.id == "END":
                        to_name = "__end__"
                    if from_name and to_name and to_name != "__end__":
                        edges.append({"from": _slugify(from_name), "to": _slugify(to_name), "mode": "sequential"})

                elif method == "add_conditional_edges" and len(call.args) >= 1:
                    source_arg = call.args[0]
                    source_name = ""
                    if isinstance(source_arg, ast.Constant):
                        source_name = str(source_arg.value)

                    # The mapping dict (3rd arg) maps condition results to target nodes
                    if len(call.args) >= 3 and isinstance(call.args[2], ast.Dict):
                        for val in call.args[2].values:
                            target_name = ""
                            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                target_name = val.value
                            elif isinstance(val, ast.Attribute) and val.attr == "END":
                                continue
                            elif isinstance(val, ast.Name) and val.id == "END":
                                continue
                            if source_name and target_name:
                                edges.append({
                                    "from": _slugify(source_name),
                                    "to": _slugify(target_name),
                                    "mode": "conditional",
                                })

                elif method == "set_entry_point" and len(call.args) >= 1:
                    if isinstance(call.args[0], ast.Constant):
                        entry_point = str(call.args[0].value)

    wf_name = kwargs.get("name", "langgraph-workflow")
    workflow = {
        "osop_version": "1.0",
        "id": _slugify(wf_name),
        "name": wf_name,
        "description": f"Imported from LangGraph — {len(nodes)} nodes.",
        "nodes": nodes,
        "edges": edges,
    }
    return yaml.dump(workflow, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ---------- EXPORTERS ----------

def export_crewai(osop_yaml: str, **kwargs: Any) -> dict[str, str]:
    """Export OSOP → CrewAI agents.yaml + tasks.yaml."""
    data = yaml.safe_load(osop_yaml) or {}
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    agents: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "agent":
            continue
        nid = node.get("id", "")
        agent: dict[str, Any] = {
            "role": node.get("name", nid),
            "goal": node.get("purpose", node.get("description", "")),
        }
        runtime = node.get("runtime", {})
        config = runtime.get("config", {}) if isinstance(runtime, dict) else {}
        if config.get("system_prompt"):
            agent["backstory"] = config["system_prompt"]
        if config.get("tools"):
            agent["tools"] = config["tools"]
        if runtime.get("model"):
            agent["llm"] = runtime["model"]
        agents[nid] = agent

    # Build task sequence from edges
    task_order: list[str] = []
    edge_map: dict[str, list[str]] = {}
    for e in edges:
        f, t = e.get("from", ""), e.get("to", "")
        edge_map.setdefault(f, []).append(t)

    # Simple topological walk
    in_deg: dict[str, int] = {n["id"]: 0 for n in nodes if isinstance(n, dict)}
    for e in edges:
        t = e.get("to", "")
        if t in in_deg:
            in_deg[t] = in_deg.get(t, 0) + 1
    queue = [nid for nid, deg in in_deg.items() if deg == 0]
    while queue:
        nid = queue.pop(0)
        if nid in agents:
            task_order.append(nid)
        for child in edge_map.get(nid, []):
            in_deg[child] -= 1
            if in_deg[child] == 0:
                queue.append(child)

    tasks: dict[str, dict] = {}
    for i, agent_id in enumerate(task_order):
        task_id = f"task_{i + 1}"
        agent_def = agents.get(agent_id, {})
        tasks[task_id] = {
            "description": agent_def.get("goal", f"Task for {agent_id}"),
            "expected_output": f"Output from {agent_def.get('role', agent_id)}",
            "agent": agent_id,
        }

    return {
        "agents.yaml": yaml.dump(agents, default_flow_style=False, sort_keys=False, allow_unicode=True),
        "tasks.yaml": yaml.dump(tasks, default_flow_style=False, sort_keys=False, allow_unicode=True),
    }


def export_n8n(osop_yaml: str, **kwargs: Any) -> str:
    """Export OSOP → n8n workflow JSON."""
    data = yaml.safe_load(osop_yaml) or {}
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    n8n_type_map = {
        "api": "n8n-nodes-base.httpRequest",
        "cli": "n8n-nodes-base.executeCommand",
        "agent": "n8n-nodes-base.code",
        "human": "n8n-nodes-base.manualTrigger",
        "db": "n8n-nodes-base.postgres",
        "system": "n8n-nodes-base.set",
        "data": "n8n-nodes-base.set",
        "git": "n8n-nodes-base.git",
        "docker": "n8n-nodes-base.executeCommand",
        "cicd": "n8n-nodes-base.executeCommand",
        "infra": "n8n-nodes-base.httpRequest",
        "mcp": "n8n-nodes-base.httpRequest",
    }

    n8n_nodes = []
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        n8n_nodes.append({
            "name": node.get("name", node.get("id", f"Node {i}")),
            "type": n8n_type_map.get(node.get("type", "system"), "n8n-nodes-base.noOp"),
            "position": [250 + i * 200, 300],
            "parameters": {},
            "typeVersion": 1,
        })

    # Build connections
    node_name_map = {_slugify(n.get("name", n.get("id", ""))): n.get("name", n.get("id", "")) for n in nodes if isinstance(n, dict)}
    connections: dict[str, dict] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        from_name = node_name_map.get(from_id, from_id)
        to_name = node_name_map.get(to_id, to_id)
        if from_name not in connections:
            connections[from_name] = {"main": [[]]}
        connections[from_name]["main"][0].append({"node": to_name, "type": "main", "index": 0})

    result = {
        "name": data.get("name", "OSOP Workflow"),
        "nodes": n8n_nodes,
        "connections": connections,
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


def export_argo(osop_yaml: str, **kwargs: Any) -> str:
    """Export OSOP → Argo Workflows YAML."""
    data = yaml.safe_load(osop_yaml) or {}
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    wf_name = _slugify(data.get("name", data.get("id", "osop-workflow")))

    # Build dependency map
    deps_map: dict[str, list[str]] = {}
    cond_map: dict[str, str] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        to_id = edge.get("to", "")
        from_id = edge.get("from", "")
        deps_map.setdefault(to_id, []).append(from_id)
        if edge.get("mode") == "conditional" and edge.get("condition"):
            cond_map[to_id] = edge["condition"]

    argo_type_map = {"docker": "container", "cli": "script", "infra": "resource"}

    # Build templates
    templates = []
    dag_tasks = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "")
        node_slug = _slugify(nid)
        template_name = f"{node_slug}-tmpl"

        # Template definition
        tmpl: dict[str, Any] = {"name": template_name}
        node_type = node.get("type", "system")
        if node_type in ("docker", "cicd"):
            tmpl["container"] = {"image": "alpine:latest", "command": ["sh", "-c"], "args": [f"echo '{node.get('name', nid)}'"]}
        elif node_type == "cli":
            tmpl["script"] = {"image": "alpine:latest", "command": ["sh"], "source": f"echo '{node.get('name', nid)}'"}
        else:
            tmpl["container"] = {"image": "alpine:latest", "command": ["echo", node.get("name", nid)]}
        templates.append(tmpl)

        # DAG task
        task: dict[str, Any] = {"name": node_slug, "template": template_name}
        if nid in deps_map:
            task["dependencies"] = [_slugify(d) for d in deps_map[nid]]
        if nid in cond_map:
            task["when"] = cond_map[nid]
        dag_tasks.append(task)

    # Main DAG template
    main_template: dict[str, Any] = {"name": "main", "dag": {"tasks": dag_tasks}}
    templates.insert(0, main_template)

    argo_wf = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {"name": wf_name, "generateName": f"{wf_name}-"},
        "spec": {"entrypoint": "main", "templates": templates},
    }
    return yaml.dump(argo_wf, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ---------- DISPATCH ----------

IMPORTERS = {
    "crewai": import_crewai,
    "n8n": import_n8n,
    "github-actions": import_github_actions,
    "airflow": import_airflow,
    "argo": import_argo,
    "langgraph": import_langgraph,
}

EXPORTERS = {
    "crewai": export_crewai,
    "n8n": export_n8n,
    "argo": export_argo,
}


def convert(
    content: str | None = None,
    file_path: str | None = None,
    source_format: str | None = None,
    target_format: str | None = None,
) -> dict[str, Any]:
    """Unified conversion dispatch.

    For import: provide source_format + content/file_path → returns OSOP YAML.
    For export: provide target_format + content/file_path (OSOP) → returns target format.
    """
    if source_format:
        # Import mode
        importer = IMPORTERS.get(source_format)
        if not importer:
            return {"error": f"Unsupported import format: {source_format}. Supported: {list(IMPORTERS.keys())}"}
        raw = content
        if not raw and file_path:
            from pathlib import Path
            raw = Path(file_path).expanduser().resolve().read_text(encoding="utf-8")
        if not raw:
            return {"error": "Either content or file_path must be provided."}
        try:
            result = importer(raw)
            return {"format": "osop", "source_format": source_format, "result": result}
        except Exception as e:
            return {"error": f"Import failed: {e}"}

    elif target_format:
        # Export mode
        exporter = EXPORTERS.get(target_format)
        if not exporter:
            return {"error": f"Unsupported export format: {target_format}. Supported: {list(EXPORTERS.keys())}"}
        raw = content
        if not raw and file_path:
            from pathlib import Path
            raw = Path(file_path).expanduser().resolve().read_text(encoding="utf-8")
        if not raw:
            return {"error": "Either content or file_path must be provided."}
        try:
            result = exporter(raw)
            return {"format": target_format, "source_format": "osop", "result": result}
        except Exception as e:
            return {"error": f"Export failed: {e}"}

    else:
        return {"error": "Provide either source_format (for import) or target_format (for export)."}
