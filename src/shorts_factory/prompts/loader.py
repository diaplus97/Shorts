"""Load prompt templates from ``prompts/`` and track their versions.

Every stage records the prompt version and file hash it used, so results can be
compared before and after a prompt edit (spec section 48).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..errors import ConfigError
from ..utils import sha256_text
from .renderer import render


def _default_prompt_dir() -> Path:
    """Mirror the config lookup: package-relative first, then the cwd."""
    candidates = [Path(__file__).resolve().parents[3] / "prompts", Path.cwd() / "prompts"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


DEFAULT_PROMPT_DIR = _default_prompt_dir()

#: Bumped by hand whenever a prompt's contract changes in a breaking way.
PROMPT_VERSIONS: dict[str, str] = {
    "research": "research-v2",
    "writer": "writer-v4",
    "director": "director-v2",
    "qa": "qa-v1",
}


class PromptPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    system: str
    user_template: str
    hash: str

    def render_user(self, variables: dict[str, object]) -> str:
        return render(self.user_template, variables)


@lru_cache(maxsize=32)
def _load(name: str, prompt_dir: str) -> PromptPair:
    directory = Path(prompt_dir) / name
    system_path = directory / "system.md"
    user_path = directory / "user.md"
    for path in (system_path, user_path):
        if not path.exists():
            raise ConfigError(f"missing prompt file: {path}")
    system = system_path.read_text(encoding="utf-8")
    user = user_path.read_text(encoding="utf-8")
    return PromptPair(
        name=name,
        version=PROMPT_VERSIONS.get(name, f"{name}-v0"),
        system=system,
        user_template=user,
        hash=sha256_text(system + "\x00" + user)[:16],
    )


def load_prompt(name: str, prompt_dir: str | Path | None = None) -> PromptPair:
    directory = Path(prompt_dir or DEFAULT_PROMPT_DIR)
    return _load(name, str(directory))
