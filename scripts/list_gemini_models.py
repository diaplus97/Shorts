#!/usr/bin/env python3
"""List the models this API key can actually see, and what each one supports.

    python scripts/list_gemini_models.py
    python scripts/list_gemini_models.py --kind video

Model ids move. veo-3.0-generate-001 was wired here from documentation and had
already been shut down, which was only discovered on the first paid call. This
asks the API instead of guessing, costs nothing, and is the right first step
before setting any model id in config.

Reads VIDEO_API_KEY from .env -- the same Gemini key the video provider uses.
The key is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from shorts_factory.providers.base import find_secret

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Substrings that sort a model into a bucket, in priority order.
KINDS: dict[str, tuple[str, ...]] = {
    "video": ("veo",),
    "image": ("imagen", "-image"),
    "tts": ("tts",),
    "embedding": ("embedding", "embed"),
    "llm": ("gemini", "gemma"),
}


def classify(name: str) -> str:
    lowered = name.lower()
    for kind, needles in KINDS.items():
        if any(needle in lowered for needle in needles):
            return kind
    return "other"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=[*KINDS, "other"], help="Show only this bucket.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--methods", action="store_true", help="Show each model's supported methods."
    )
    return parser.parse_args()


async def fetch_models(base_url: str, api_key: str) -> list[dict]:
    models: list[dict] = []
    page: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {"pageSize": "200"}
            if page:
                params["pageToken"] = page
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"x-goog-api-key": api_key},
                params=params,
            )
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
            body = response.json()
            models.extend(body.get("models", []))
            page = body.get("nextPageToken")
            if not page:
                return models


async def main() -> int:
    args = parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    found = find_secret("VIDEO_API_KEY")
    api_key = found[1] if found else None
    if not api_key:
        print("FAIL: VIDEO_API_KEY is not set. Put your Gemini key in .env")
        return 1

    try:
        models = await fetch_models(args.base_url, api_key)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    buckets: dict[str, list[dict]] = {}
    for model in models:
        buckets.setdefault(classify(model.get("name", "")), []).append(model)

    order = [args.kind] if args.kind else [*KINDS, "other"]
    shown = 0
    for kind in order:
        entries = buckets.get(kind)
        if not entries:
            continue
        print(f"\n=== {kind} ({len(entries)}) ===")
        for model in sorted(entries, key=lambda m: m.get("name", "")):
            # "models/veo-3.1-fast-generate-preview" -> the id you put in config
            model_id = model.get("name", "").removeprefix("models/")
            print(f"  {model_id}")
            if display := model.get("displayName"):
                print(f"      {display}")
            if args.methods and (methods := model.get("supportedGenerationMethods")):
                print(f"      methods: {', '.join(methods)}")
            shown += 1

    print(f"\n{shown} model(s). Put an id from here into config/settings.local.yaml.")
    print("A model missing from this list is not available to this key, whatever")
    print("the documentation says.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
