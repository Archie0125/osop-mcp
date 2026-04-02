"""Tests for tools/render.py — Rendering OSOP workflows as diagrams."""

from __future__ import annotations

import textwrap

import pytest

from tools.render import render


class TestRenderMermaid:
    """Tests for Mermaid diagram rendering."""

    def test_mermaid_output_format(self, valid_yaml):
        result = render(content=valid_yaml, format="mermaid")
        assert result["format"] == "mermaid"
        assert "diagram" in result

    def test_mermaid_starts_with_graph_directive(self, valid_yaml):
        result = render(content=valid_yaml, format="mermaid")
        assert result["diagram"].startswith("graph TB")

    def test_mermaid_contains_node_ids(self, valid_yaml):
        result = render(content=valid_yaml, format="mermaid")
        diagram = result["diagram"]
        assert "step_a" in diagram
        assert "step_b" in diagram

    def test_mermaid_contains_node_labels(self, valid_yaml):
        result = render(content=valid_yaml, format="mermaid")
        diagram = result["diagram"]
        assert '"Step A"' in diagram
        assert '"Step B"' in diagram

    def test_mermaid_contains_edge_arrow(self, valid_yaml):
        result = render(content=valid_yaml, format="mermaid")
        diagram = result["diagram"]
        # sequential edge: step_a --> step_b
        assert "-->" in diagram

    def test_mermaid_direction_lr(self, valid_yaml):
        result = render(content=valid_yaml, format="mermaid", direction="LR")
        assert result["diagram"].startswith("graph LR")

    def test_mermaid_human_node_shape(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "shapes"
            name: "Shape Test"
            nodes:
              - id: "h"
                type: "human"
                name: "Human Step"
            edges: []
        """)
        result = render(content=yaml_str, format="mermaid")
        # Human nodes use stadium shape ([" ... "])
        assert '(["Human Step"' in result["diagram"]

    def test_mermaid_agent_node_shape(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "shapes"
            name: "Shape Test"
            nodes:
              - id: "ag"
                type: "agent"
                name: "Agent Step"
            edges: []
        """)
        result = render(content=yaml_str, format="mermaid")
        # Agent nodes use hexagon shape ({{ ... }})
        assert '{{"Agent Step"' in result["diagram"]

    def test_mermaid_conditional_edge(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "cond"
            name: "Conditional"
            nodes:
              - id: "a"
                type: "cli"
                name: "A"
              - id: "b"
                type: "cli"
                name: "B"
            edges:
              - from: "a"
                to: "b"
                mode: "conditional"
                when: "status == ok"
        """)
        result = render(content=yaml_str, format="mermaid")
        diagram = result["diagram"]
        assert "-.->|status == ok|" in diagram

    def test_mermaid_parallel_edge(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "par"
            name: "Parallel"
            nodes:
              - id: "a"
                type: "cli"
                name: "A"
              - id: "b"
                type: "cli"
                name: "B"
            edges:
              - from: "a"
                to: "b"
                mode: "parallel"
        """)
        result = render(content=yaml_str, format="mermaid")
        assert "==>" in result["diagram"]

    def test_mermaid_fallback_edge(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "fb"
            name: "Fallback"
            nodes:
              - id: "a"
                type: "cli"
                name: "A"
              - id: "b"
                type: "cli"
                name: "B"
            edges:
              - from: "a"
                to: "b"
                mode: "fallback"
        """)
        result = render(content=yaml_str, format="mermaid")
        assert "fallback" in result["diagram"]


class TestRenderAscii:
    """Tests for ASCII diagram rendering."""

    def test_ascii_output_format(self, valid_yaml):
        result = render(content=valid_yaml, format="ascii")
        assert result["format"] == "ascii"
        assert "diagram" in result

    def test_ascii_contains_node_info(self, valid_yaml):
        result = render(content=valid_yaml, format="ascii")
        diagram = result["diagram"]
        assert "[cli] step_a: Step A" in diagram
        assert "[api] step_b: Step B" in diagram

    def test_ascii_contains_edge_info(self, valid_yaml):
        result = render(content=valid_yaml, format="ascii")
        diagram = result["diagram"]
        assert "step_a --sequential--> step_b" in diagram

    def test_ascii_edge_label(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "labeled"
            name: "Labeled"
            nodes:
              - id: "a"
                type: "cli"
                name: "A"
              - id: "b"
                type: "cli"
                name: "B"
            edges:
              - from: "a"
                to: "b"
                mode: "sequential"
                label: "next step"
        """)
        result = render(content=yaml_str, format="ascii")
        assert "(next step)" in result["diagram"]


class TestRenderUnsupportedFormat:
    """Tests for unsupported format handling."""

    def test_unsupported_format_returns_error(self, valid_yaml):
        result = render(content=valid_yaml, format="svg")
        assert "error" in result
        assert "Unsupported format" in result["error"]

    def test_unknown_format_returns_error(self, valid_yaml):
        result = render(content=valid_yaml, format="pdf")
        assert "error" in result


class TestRenderInvalidInput:
    """Tests for invalid input handling."""

    def test_non_dict_yaml_raises(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            render(content="- just a list\n")

    def test_empty_workflow(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "empty"
            name: "Empty"
            nodes: []
            edges: []
        """)
        result = render(content=yaml_str, format="mermaid")
        assert result["format"] == "mermaid"
        assert "graph TB" in result["diagram"]

    def test_render_from_file(self, valid_yaml_file):
        result = render(file_path=valid_yaml_file, format="mermaid")
        assert result["format"] == "mermaid"
        assert "step_a" in result["diagram"]
