"""osop.validate — Validate OSOP YAML against the JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .common import load_yaml

# Load the schema once at import time
_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "osop-spec" / "schema" / "osop.schema.json"
_SCHEMA: dict | None = None


def _get_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        if _SCHEMA_PATH.exists():
            _SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        else:
            raise FileNotFoundError(f"OSOP schema not found at {_SCHEMA_PATH}")
    return _SCHEMA


def validate(
    content: str | None = None,
    file_path: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Validate an OSOP workflow against the JSON Schema.

    Returns dict with: valid (bool), errors (list), warnings (list).
    """
    raw, parsed = load_yaml(content, file_path)
    schema = _get_schema()

    errors: list[dict] = []
    warnings: list[dict] = []

    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(parsed), key=lambda e: list(e.path)):
        entry = {
            "path": ".".join(str(p) for p in error.absolute_path) or "(root)",
            "message": error.message,
        }
        errors.append(entry)

    # Structural warnings
    nodes = parsed.get("nodes", [])
    edges = parsed.get("edges", [])
    node_ids = {n.get("id") for n in nodes if isinstance(n, dict)}

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for field in ("from", "to"):
            ref = edge.get(field)
            if ref and ref not in node_ids:
                warnings.append({"path": f"edges.{field}", "message": f"Edge references unknown node: {ref}"})

    # Orphan node check
    referenced = set()
    for edge in edges:
        if isinstance(edge, dict):
            referenced.add(edge.get("from"))
            referenced.add(edge.get("to"))
    for nid in node_ids:
        if nid not in referenced:
            warnings.append({"path": f"nodes.{nid}", "message": f"Node '{nid}' is not connected by any edge."})

    is_valid = len(errors) == 0 and (not strict or len(warnings) == 0)

    return {
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
