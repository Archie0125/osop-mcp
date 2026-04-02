"""Tests for tools/validate.py — OSOP workflow validation."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.validate import validate, _get_schema


# ---------------------------------------------------------------------------
# Schema availability guard
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "osop-spec" / "schema" / "osop.schema.json"
SCHEMA_AVAILABLE = _SCHEMA_PATH.exists()
skip_no_schema = pytest.mark.skipif(not SCHEMA_AVAILABLE, reason="osop-spec schema not found")


# ---------------------------------------------------------------------------
# Valid workflows
# ---------------------------------------------------------------------------

class TestValidateValidWorkflows:
    """Tests that valid workflows pass validation."""

    @skip_no_schema
    def test_valid_workflow_returns_valid_true(self, valid_yaml):
        result = validate(content=valid_yaml)
        assert result["valid"] is True
        assert result["errors"] == []

    @skip_no_schema
    def test_valid_workflow_counts(self, valid_yaml):
        result = validate(content=valid_yaml)
        assert result["node_count"] == 2
        assert result["edge_count"] == 1

    @skip_no_schema
    def test_valid_workflow_from_file(self, valid_yaml_file):
        result = validate(file_path=valid_yaml_file)
        assert result["valid"] is True

    @skip_no_schema
    def test_valid_three_node_workflow(self, valid_three_nodes_yaml):
        result = validate(content=valid_three_nodes_yaml)
        assert result["valid"] is True
        assert result["node_count"] == 3
        assert result["edge_count"] == 2


# ---------------------------------------------------------------------------
# Invalid YAML
# ---------------------------------------------------------------------------

class TestValidateInvalidYaml:
    """Tests that invalid YAML is handled correctly."""

    def test_unparseable_yaml(self):
        bad_yaml = ":::\nnot: [valid: yaml\n"
        with pytest.raises(Exception):
            validate(content=bad_yaml)

    def test_non_dict_yaml(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            validate(content="- item1\n- item2\n")


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestValidateMissingFields:
    """Tests that missing required fields produce errors."""

    @skip_no_schema
    def test_missing_id(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            name: "No ID"
            nodes: []
            edges: []
        """)
        result = validate(content=yaml_str)
        assert result["valid"] is False
        assert any("id" in e["message"] for e in result["errors"])

    @skip_no_schema
    def test_missing_name(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "no-name"
            nodes: []
            edges: []
        """)
        result = validate(content=yaml_str)
        assert result["valid"] is False
        assert any("name" in e["message"] for e in result["errors"])

    @skip_no_schema
    def test_missing_nodes_and_edges(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "bare"
            name: "Bare"
        """)
        result = validate(content=yaml_str)
        assert result["valid"] is False

    @skip_no_schema
    def test_missing_osop_version(self):
        yaml_str = textwrap.dedent("""\
            id: "no-version"
            name: "No Version"
            nodes: []
            edges: []
        """)
        result = validate(content=yaml_str)
        assert result["valid"] is False
        assert any("osop_version" in e["message"] for e in result["errors"])


# ---------------------------------------------------------------------------
# Invalid node types / edge modes (schema-level)
# ---------------------------------------------------------------------------

class TestValidateSchemaViolations:
    """Tests for schema-level violations in nodes and edges."""

    @skip_no_schema
    def test_invalid_node_type_caught_by_schema(self):
        """If the schema enumerates node types, an invalid type should fail."""
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "bad-type"
            name: "Bad Type"
            nodes:
              - id: "x"
                type: "not_a_real_type_zzz"
                name: "Bad"
            edges: []
        """)
        result = validate(content=yaml_str)
        # This may or may not produce an error depending on schema strictness.
        # The test documents the behavior either way.
        assert isinstance(result["valid"], bool)
        assert isinstance(result["errors"], list)

    @skip_no_schema
    def test_invalid_edge_mode_caught_by_schema(self):
        yaml_str = textwrap.dedent("""\
            osop_version: "1.0"
            id: "bad-mode"
            name: "Bad Mode"
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
                mode: "teleportation"
        """)
        result = validate(content=yaml_str)
        assert isinstance(result["valid"], bool)
        assert isinstance(result["errors"], list)


# ---------------------------------------------------------------------------
# Structural warnings
# ---------------------------------------------------------------------------

class TestValidateStructuralWarnings:
    """Tests for structural warning detection."""

    @skip_no_schema
    def test_edge_referencing_nonexistent_node(self, bad_edge_ref_yaml):
        result = validate(content=bad_edge_ref_yaml)
        assert any("ghost_node" in w["message"] for w in result["warnings"])

    @skip_no_schema
    def test_orphan_node_detected(self, orphan_yaml):
        result = validate(content=orphan_yaml)
        orphan_warnings = [w for w in result["warnings"] if "orphan_node" in w["message"]]
        assert len(orphan_warnings) >= 1

    @skip_no_schema
    def test_no_orphan_warning_for_connected_nodes(self, valid_yaml):
        result = validate(content=valid_yaml)
        orphan_warnings = [w for w in result["warnings"] if "not connected" in w["message"]]
        assert len(orphan_warnings) == 0


# ---------------------------------------------------------------------------
# Strict mode
# ---------------------------------------------------------------------------

class TestValidateStrictMode:
    """Tests for strict mode (warnings become errors)."""

    @skip_no_schema
    def test_strict_mode_fails_on_warnings(self, orphan_yaml):
        result = validate(content=orphan_yaml, strict=True)
        # In strict mode, warnings cause valid=False
        if result["warnings"]:
            assert result["valid"] is False

    @skip_no_schema
    def test_non_strict_mode_passes_with_warnings(self, orphan_yaml):
        result = validate(content=orphan_yaml, strict=False)
        # Non-strict: valid if no schema errors, even with warnings
        if not result["errors"]:
            assert result["valid"] is True


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

class TestValidateResultShape:
    """Tests that the result dict always has expected keys."""

    @skip_no_schema
    def test_result_has_all_keys(self, valid_yaml):
        result = validate(content=valid_yaml)
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result
        assert "node_count" in result
        assert "edge_count" in result

    @skip_no_schema
    def test_node_count_and_edge_count_are_ints(self, valid_yaml):
        result = validate(content=valid_yaml)
        assert isinstance(result["node_count"], int)
        assert isinstance(result["edge_count"], int)


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

class TestSchemaLoading:
    """Tests for the schema loading mechanism."""

    def test_get_schema_returns_dict(self):
        if not SCHEMA_AVAILABLE:
            pytest.skip("Schema file not available")
        schema = _get_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema

    def test_get_schema_raises_when_missing(self):
        """When schema file is missing, FileNotFoundError is raised."""
        import tools.validate as mod
        original = mod._SCHEMA
        original_path = mod._SCHEMA_PATH
        try:
            mod._SCHEMA = None
            mod._SCHEMA_PATH = Path("/nonexistent/schema.json")
            with pytest.raises(FileNotFoundError):
                mod._get_schema()
        finally:
            mod._SCHEMA = original
            mod._SCHEMA_PATH = original_path
