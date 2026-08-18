"""Structured logging: human console output plus an optional project JSONL file.

API keys must never reach either sink (spec section 49), so a redaction
processor runs before any renderer.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import structlog

from .files import ensure_dir

_SECRET_KEY_PATTERN = re.compile(r"(key|token|secret|password|authorization)", re.IGNORECASE)
_SECRET_ENV_NAMES = (
    "OPENAI_API_KEY",
    "SEARCH_API_KEY",
    "IMAGE_API_KEY",
    "VIDEO_API_KEY",
    "TTS_API_KEY",
)
_REDACTED = "***redacted***"

#: Set by :func:`bind_project_log`; ``None`` means console-only logging.
_json_log_path: Path | None = None
_configured = False


def _secret_values() -> list[str]:
    values = []
    for name in _SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            values.append(value)
    return values


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    secrets = _secret_values()
    for key, value in list(event_dict.items()):
        if _SECRET_KEY_PATTERN.search(key):
            event_dict[key] = _REDACTED
            continue
        if isinstance(value, str):
            for secret in secrets:
                if secret in value:
                    value = value.replace(secret, _REDACTED)
            event_dict[key] = value
    return event_dict


def _json_sink(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    if _json_log_path is not None:
        with (
            contextlib.suppress(OSError),
            _json_log_path.open("a", encoding="utf-8") as handle,
        ):
            handle.write(json.dumps(event_dict, ensure_ascii=False, default=str) + "\n")
    return event_dict


class _StderrLogger:
    """Writes to whatever ``sys.stderr`` is at call time.

    structlog's PrintLogger captures the stream when it is built. Anything that
    swaps stderr afterwards -- a CLI test runner, a capture fixture -- leaves it
    writing to a closed file.
    """

    def msg(self, message: str) -> None:
        # Logging must never take the pipeline down.
        with contextlib.suppress(ValueError, OSError):
            print(message, file=sys.stderr, flush=True)

    log = debug = info = warning = warn = error = critical = exception = fatal = msg


class _StderrLoggerFactory:
    def __call__(self, *args: Any) -> _StderrLogger:
        return _StderrLogger()


def configure_logging(level: str = "INFO", *, force: bool = False) -> None:
    global _configured
    if _configured and not force:
        return
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_secrets,
            _json_sink,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=_StderrLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured = True


def bind_project_log(path: str | Path | None) -> None:
    """Route every subsequent log line into ``path`` as JSONL as well."""
    global _json_log_path
    if path is None:
        _json_log_path = None
        return
    target = Path(path)
    ensure_dir(target.parent)
    _json_log_path = target


def get_logger(name: str = "shorts_factory") -> Any:
    configure_logging()
    return structlog.get_logger(name)
