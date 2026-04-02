"""Tests for tools/common.py — shared utilities."""

from __future__ import annotations

import pytest

from tools.common import load_yaml


class TestLoadYaml:
    """Tests for the load_yaml utility."""

    def test_load_from_content_string(self, valid_yaml):
        raw, parsed = load_yaml(content=valid_yaml)
        assert isinstance(raw, str)
        assert isinstance(parsed, dict)
        assert parsed["id"] == "test-workflow"
        assert parsed["name"] == "Test Workflow"

    def test_load_from_file_path(self, valid_yaml_file):
        raw, parsed = load_yaml(file_path=valid_yaml_file)
        assert isinstance(raw, str)
        assert isinstance(parsed, dict)
        assert parsed["id"] == "test-workflow"

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError, match="File not found"):
            load_yaml(file_path="/nonexistent/path/to/file.osop.yaml")

    def test_neither_content_nor_file_raises(self):
        with pytest.raises(ValueError, match="Either 'content' or 'file_path'"):
            load_yaml()

    def test_non_dict_yaml_raises(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            load_yaml(content="- item1\n- item2\n")

    def test_scalar_yaml_raises(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            load_yaml(content="just a string")

    def test_content_takes_precedence_over_file_path(self, valid_yaml_file):
        """When both content and file_path are given, content wins."""
        alt_yaml = 'osop_version: "1.0"\nid: "from-content"\nname: "Content"\nnodes: []\nedges: []\n'
        raw, parsed = load_yaml(content=alt_yaml, file_path=valid_yaml_file)
        assert parsed["id"] == "from-content"

    def test_empty_dict_yaml(self):
        raw, parsed = load_yaml(content="{}")
        assert parsed == {}

    def test_parsed_preserves_nested_structure(self, valid_yaml):
        _, parsed = load_yaml(content=valid_yaml)
        assert isinstance(parsed["nodes"], list)
        assert len(parsed["nodes"]) == 2
        assert parsed["nodes"][0]["id"] == "step_a"
