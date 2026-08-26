#!/usr/bin/env python3
"""Make one call of each kind and print exactly what the API says back.

    python scripts/probe_gemini.py                 # search grounding + plain LLM
    python scripts/probe_gemini.py --kind llm

A 429 on a first request is usually not "too fast" -- it is a quota that is
zero for that model, that feature, or that billing tier. Google says which in
the response body, and the pipeline's retry wrapper hides it behind four
attempts. This asks once and prints the answer verbatim.

Costs at most a few cents, and nothing at all when the answer is a refusal.
The key is read from .env and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from shorts_factory.providers.base import find_secret

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=["search", "llm", "both"],
        default="both",
        help="search = grounded call (the one that 429'd); llm = plain generateContent.",
    )
    parser.add_argument("--model", help="Override the model id to test.")
    parser.add_argument("--base-url", default=BASE_URL)
    return parser.parse_args()


async def call(url: str, api_key: str, payload: dict) -> tuple[int, str]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        return response.status_code, response.text


def report(label: str, model: str, status: int, text: str) -> None:
    print(f"\n=== {label}  ({model}) ===")
    print(f"  HTTP {status}")
    if status == 200:
        print("  OK — this call works.")
        return
    try:
        error = json.loads(text).get("error", {})
    except ValueError:
        print(f"  {text[:600]}")
        return
    print(f"  status : {error.get('status')}")
    print(f"  message: {error.get('message')}")
    # The quota failure details name the exact metric that is at zero, which is
    # what separates "slow down" from "this is not enabled for your key".
    for detail in error.get("details", []):
        kind = str(detail.get("@type", "")).rsplit(".", 1)[-1]
        if kind == "QuotaFailure":
            for violation in detail.get("violations", []):
                print(f"  quota  : {violation.get('quotaId') or violation.get('subject')}")
                if description := violation.get("description"):
                    print(f"           {description}")
                if value := violation.get("quotaValue"):
                    print(f"           limit {value}")
        elif kind == "Help":
            for link in detail.get("links", []):
                print(f"  help   : {link.get('url')}")
        elif kind == "RetryInfo":
            print(f"  retry  : {detail.get('retryDelay')}")


async def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)

    checks: list[tuple[str, str, str, dict]] = []
    if args.kind in ("search", "both"):
        model = args.model or os.environ.get("PROBE_SEARCH_MODEL") or "gemini-3.7-flash"
        checks.append(
            (
                "search grounding",
                "SEARCH_API_KEY",
                model,
                {
                    "contents": [{"parts": [{"text": "What is an ATM cash deposit module?"}]}],
                    "tools": [{"google_search": {}}],
                },
            )
        )
    if args.kind in ("llm", "both"):
        model = args.model or os.environ.get("PROBE_LLM_MODEL") or "gemini-3.7-flash"
        checks.append(
            (
                "plain generateContent",
                "LLM_API_KEY",
                model,
                {"contents": [{"parts": [{"text": "Reply with the single word: ok"}]}]},
            )
        )

    failures = 0
    for label, env_name, model, payload in checks:
        found = find_secret(env_name)
        api_key = found[1] if found else None
        if not api_key:
            print(f"\n=== {label} ===\n  SKIP — {env_name} is not set in .env")
            failures += 1
            continue
        status, text = await call(
            f"{args.base_url}/models/{model}:generateContent", api_key, payload
        )
        report(label, model, status, text)
        if status != 200:
            failures += 1

    print()
    if failures:
        print("Grounding and plain generation are billed and quota'd separately, so one")
        print("failing while the other works is normal and tells you which to fix.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
