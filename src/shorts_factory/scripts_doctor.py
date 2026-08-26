"""Environment diagnostics behind ``shorts doctor``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import AppConfig, active_local_overrides, load_config
from .errors import ConfigError
from .media import ffmpeg
from .prompts import PROMPT_VERSIONS, load_prompt
from .providers.base import find_secret

#: Lowest interpreter this package supports; mirrors requires-python.
MINIMUM_PYTHON = (3, 12)

#: Which secret each non-mock provider needs. Presence only -- never the value.
REQUIRED_SECRETS = {
    "llm": {"openai": "OPENAI_API_KEY", "gemini": "LLM_API_KEY"},
    "search": {"gemini": "SEARCH_API_KEY"},
    "image": {"gemini": "IMAGE_API_KEY"},
    "video": {"veo": "VIDEO_API_KEY", "fal": "FAL_KEY"},
    "tts": {"openai": "TTS_API_KEY", "gemini": "TTS_API_KEY"},
}


def _ok(message: str) -> bool:
    print(f"  [ok]   {message}")
    return True


def _warn(message: str) -> bool:
    print(f"  [warn] {message}")
    return True


def _bad(message: str) -> bool:
    print(f"  [FAIL] {message}")
    return False


def check_python() -> bool:
    if sys.version_info[:2] >= MINIMUM_PYTHON:
        return _ok(f"python {sys.version.split()[0]}")
    required = ".".join(str(part) for part in MINIMUM_PYTHON)
    return _bad(f"python {sys.version.split()[0]} — {required} or newer is required")


def check_config(config_dir: Path | None) -> tuple[bool, AppConfig | None]:
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        return _bad(f"configuration: {exc}"), None
    _ok(f"configuration loaded from {config.config_dir}")
    # Running against settings you cannot see in `git diff` is worth saying out
    # loud -- otherwise "it works for me" and "it fails for you" have no visible
    # cause. This is a warning rather than a failure: overrides are the point.
    for override in active_local_overrides(config.config_dir):
        _warn(f"local override in effect: {override.name} (gitignored)")
    return True, config


def check_prompts() -> bool:
    healthy = True
    for name, version in PROMPT_VERSIONS.items():
        try:
            prompt = load_prompt(name)
        except ConfigError as exc:
            healthy = _bad(f"prompt '{name}': {exc}") and healthy
            continue
        _ok(f"prompt {name} ({version}, hash {prompt.hash})")
    return healthy


def check_ffmpeg() -> bool:
    if not ffmpeg.is_available():
        return _bad("ffmpeg/ffprobe not found on PATH — install ffmpeg")
    _ok(ffmpeg.version())
    if ffmpeg.has_filter("subtitles"):
        _ok("ffmpeg has the 'subtitles' filter (libass) for burn-in")
    else:
        _warn("no 'subtitles' filter; set subtitles.burn_in: false or install a full ffmpeg")
    # Only the mock preview's watermark needs this, so it is not fatal -- but
    # doctor passing and compose then dying on a missing filter is exactly the
    # failure this command exists to prevent.
    if ffmpeg.has_filter("drawtext"):
        _ok("ffmpeg has the 'drawtext' filter for the mock preview watermark")
    else:
        _warn(
            "no 'drawtext' filter (needs libfreetype); mock previews will be marked "
            "with a magenta border instead of text. final.mp4 is unaffected"
        )
    return True


def check_font(config: AppConfig | None) -> bool:
    if config is None:
        return True
    name = config.settings.subtitles.font_name
    if not shutil.which("fc-list"):
        return _warn(f"fontconfig not available; cannot verify the subtitle font '{name}'")
    result = subprocess.run(
        ["fc-list", ":lang=ko", "family"], capture_output=True, text=True, check=False
    )
    if name.lower() in result.stdout.lower():
        return _ok(f"subtitle font '{name}' is installed")
    families = sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
    if families:
        return _warn(
            f"subtitle font '{name}' not found. Korean-capable families here: {families[:5]}"
        )
    return _warn("no Korean-capable font installed; burned-in subtitles will not render")


def check_providers(config: AppConfig | None) -> bool:
    if config is None:
        return True
    healthy = True
    for kind, provider in config.settings.providers.as_dict().items():
        secret_name = REQUIRED_SECRETS.get(kind, {}).get(provider)
        if provider == "mock":
            _ok(f"{kind}: mock (no credentials needed)")
        elif secret_name is None:
            healthy = _bad(f"{kind}: '{provider}' has no implementation registered") and healthy
        elif (found := find_secret(secret_name)) is not None:
            name, _ = found
            label = name if name == secret_name else f"{name}, accepted for {secret_name}"
            _ok(f"{kind}: {provider} ({label} is set)")
        else:
            healthy = _bad(f"{kind}: {provider} needs {secret_name}; add it to .env") and healthy
            _suggest_similar(secret_name)
    return healthy


def _env_file() -> Path | None:
    """The .env python-dotenv would have loaded, for saying where to look."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def env_key_names(path: Path | None = None) -> list[str]:
    """The variable NAMES in the .env file. Never the values.

    Printing which keys exist is the difference between "FAL_KEY is not set" --
    which is true and useless -- and seeing that the file has FAL_API_KEY in it,
    or that it has the Gemini keys and no fal one at all because only what was
    needed at the time got copied across.
    """
    target = path or _env_file()
    if target is None:
        return []
    names: list[str] = []
    try:
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip().removeprefix("export ").strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name = line.split("=", 1)[0].strip()
            if name:
                names.append(name)
    except OSError:
        return []
    return names


def _suggest_similar(wanted: str) -> None:
    """Point at a key that looks like the missing one, when there is one."""
    present = env_key_names()
    if not present:
        path = _env_file()
        print(
            f"     no .env found from {Path.cwd()} upwards"
            if path is None
            else f"     {path} has no readable entries"
        )
        return
    stem = wanted.replace("_API_KEY", "").replace("_KEY", "")
    close = [n for n in present if stem and stem in n and n != wanted]
    print(f"     .env is {_env_file()} and has: {', '.join(sorted(present))}")
    if close:
        print(f"     did you mean one of these? {', '.join(close)}")


def check_project_root(config: AppConfig | None) -> bool:
    if config is None:
        return True
    root = Path(config.settings.project_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return _bad(f"project root {root} is not writable: {exc}")
    return _ok(f"project root {root} is writable")


def check_live_api_guard() -> bool:
    if os.environ.get("ALLOW_LIVE_API_TESTS") == "1":
        return _warn("ALLOW_LIVE_API_TESTS=1 — paid APIs are reachable from tests")
    return _ok("live API calls are blocked in tests")


def run_doctor(config_dir: str | Path | None = None) -> bool:
    directory = Path(config_dir) if config_dir else None
    print("shorts doctor")
    results = [check_python()]
    config_ok, config = check_config(directory)
    results.append(config_ok)
    results.append(check_prompts())
    results.append(check_ffmpeg())
    results.append(check_font(config))
    results.append(check_providers(config))
    results.append(check_project_root(config))
    results.append(check_live_api_guard())
    healthy = all(results)
    print("\nOK" if healthy else "\nPROBLEMS FOUND")
    return healthy
