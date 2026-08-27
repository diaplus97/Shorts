"""Minimal ``{{variable}}`` template renderer.

Deliberately not Jinja: prompts should stay readable text files, and a template
engine invites logic to creep into prompts (spec section 48).
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import ConfigError

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render(template: str, variables: dict[str, Any]) -> str:
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.append(key)
            return match.group(0)
        return _stringify(variables[key])

    rendered = _PLACEHOLDER.sub(_replace, template)
    if missing:
        raise ConfigError(f"prompt template is missing variables: {sorted(set(missing))}")
    return rendered


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, indent=2)


def unused_variables(template: str, variables: dict[str, Any]) -> list[str]:
    used = {match.group(1) for match in _PLACEHOLDER.finditer(template)}
    return sorted(set(variables) - used)
