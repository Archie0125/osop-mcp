"""osop.validate — Validate OSOP YAML against the JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .common import load_yaml

# Load schemas once at import time
_SPEC_DIR = Path(__file__).resolve().parent.parent.parent / "osop-spec" / "schema"
_SCHEMAS: dict[str, dict] = {}


def _get_schema(variant: str = "core") -> dict:
    if variant not in _SCHEMAS:
        filename = "osop-core.schema.json" if variant == "core" else "osop.schema.json"
        path = _SPEC_DIR / filename
        if path.exists():
            _SCHEMAS[variant] = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise FileNotFoundError(f"OSOP schema not found at {path}")
    return _SCHEMAS[variant]


def validate(
    content: str | None = None,
    file_path: str | None = None,
    strict: bool = False,
    schema_variant: str = "core",
) -> dict[str, Any]:
    """Validate an OSOP workflow against the JSON Schema.

    Returns dict with: valid (bool), errors (list), warnings (list).
    """
    raw, parsed = load_yaml(content, file_path)
    schema = _get_schema(schema_variant)

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
