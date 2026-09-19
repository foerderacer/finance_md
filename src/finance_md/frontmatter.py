"""Minimal YAML frontmatter handling (split, load, dump)."""

from __future__ import annotations

from typing import Any

import yaml

from .errors import ParseError

DELIMITER = "---"


def split_frontmatter(text: str, file: str = "<text>") -> tuple[str, str, int]:
    """Split *text* into (yaml block, body, line number of the closing delimiter).

    Line numbers are 1-based. Raises ParseError if the frontmatter is missing
    or unterminated.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != DELIMITER:
        raise ParseError(file, 1, "missing YAML frontmatter (file must start with '---')")
    for index in range(1, len(lines)):
        if lines[index].strip() == DELIMITER:
            yaml_text = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return yaml_text, body, index + 1
    raise ParseError(file, 1, "unterminated YAML frontmatter (missing closing '---')")


def load_yaml(yaml_text: str, file: str, line: int) -> dict[str, Any]:
    """Load frontmatter YAML strictly, raising ParseError on invalid YAML."""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ParseError(file, line, f"invalid YAML frontmatter: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ParseError(file, line, "frontmatter must be a YAML mapping")
    return data


def dump_yaml(value: Any) -> str:
    """Dump a scalar or mapping as YAML in a stable, human-friendly form."""
    return yaml.safe_dump(value, default_flow_style=False, sort_keys=False, allow_unicode=True)
