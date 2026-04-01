"""Common utilities for OSOP MCP tools."""

from __future__ import annotations

import yaml
from pathlib import Path


def load_yaml(content: str | None = None, file_path: str | None = None) -> tuple[str, dict]:
    """Load YAML from content string or file path. Returns (raw_text, parsed_dict)."""
    if content:
        raw = content
    elif file_path:
        p = Path(file_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        raw = p.read_text(encoding="utf-8")
    else:
        raise ValueError("Either 'content' or 'file_path' must be provided.")

    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ValueError("YAML content must be a mapping (dict), not a sequence or scalar.")
    return raw, parsed
