"""Helpers for reading the machine-readable blocks the prompt templates emit.

The mock LLM reads the same ``KEY: value`` lines and ``NAME_JSON`` fenced blocks
that a real model sees, so the mock exercises the real prompt-rendering path
instead of a parallel one.
"""

from __future__ import annotations

import json
import re
from typing import Any


def field(prompt: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", prompt, re.MULTILINE)
    return match.group(1).strip() if match else default


def float_field(prompt: str, key: str, default: float) -> float:
    raw = field(prompt, key)
    try:
        return float(raw)
    except ValueError:
        return default


def int_field(prompt: str, key: str, default: int) -> int:
    return int(float_field(prompt, key, float(default)))


def json_block(prompt: str, label: str, default: Any = None) -> Any:
    match = re.search(
        rf"^{re.escape(label)}:\s*\n```json\s*\n(.*?)\n```",
        prompt,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return default
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return default
