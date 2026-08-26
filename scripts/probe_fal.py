#!/usr/bin/env python3
"""Make one fal.ai call and print exactly what comes back.

    python scripts/probe_fal.py
    python scripts/probe_fal.py --model fal-ai/kling-video/v2.6/pro/image-to-video

Every model on fal has its own input schema, and this adapter has never been run
against the live service. Finding a wrong field name inside a full run costs a
scene and the money already spent on it; finding it here costs one clip.

Prints the request that was sent and the raw response at every step, so a
rejected field, a renamed output key or an auth problem is visible rather than
inferred. The key is read from .env and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx
from dotenv import load_dotenv

BASE_URL = "https://queue.fal.run"
DEFAULT_MODEL = "fal-ai/wan/v2.6/image-to-video"

#: A 2x2 red PNG, so image-to-video can be exercised without generating a still
#: first. Enough to prove the field is accepted; not enough to look at.
TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEUlEQVR4nGP8z4"
    "AATAxIHAgLAA6VAQU8OKvHAAAAAElFTkSuQmCC"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Default: {DEFAULT_MODEL}")
    parser.add_argument("--prompt", default="a slow push in on a metal roller, technical cutaway")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Send text-to-video instead, to see whether image_url is what is rejected.",
    )
    parser.add_argument("--timeout", type=float, default=420.0, help="Give up polling after this.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    load_dotenv(override=False)
    key = os.environ.get("FAL_KEY")
    if not key:
        # "FAL_KEY is not set" on its own is true and useless. Which .env was
        # read, and what is actually in it, is the part that answers the
        # question -- usually that the key is there under another name, or that
        # only the keys needed at the time ever got copied into this project.
        from shorts_factory.scripts_doctor import _suggest_similar

        print("FAIL: FAL_KEY is not set.")
        _suggest_similar("FAL_KEY")
        print("\n  To copy it across from another .env without printing it:")
        print("    grep -h '^FAL' /path/to/other/.env >> ~/Shorts/.env")
        return 1

    model = args.model.strip("/")
    headers = {"Authorization": f"Key {key}"}
    payload: dict = {
        "prompt": args.prompt,
        "duration": args.duration,
        "aspect_ratio": "9:16",
    }
    if not args.no_image:
        payload["image_url"] = f"data:image/png;base64,{TINY_PNG}"

    shown = {k: (v[:48] + "...") if k == "image_url" else v for k, v in payload.items()}
    print(f"\n  model   {model}")
    print(f"  request {json.dumps(shown, ensure_ascii=False)}\n")

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{BASE_URL}/{model}", headers=headers, json=payload)
        print(f"  submit  HTTP {response.status_code}")
        print(f"          {response.text[:600]}\n")
        if response.status_code >= 400:
            print("  The message above names what fal did not accept. A wrong field")
            print("  name is a config change (video.duration_field / aspect_ratio_field")
            print("  / extra_parameters), not a code change.")
            return 1

        request_id = response.json().get("request_id")
        if not request_id:
            print("  FAIL: no request_id in the reply, so there is nothing to poll.")
            return 1

        waited = 0.0
        while waited < args.timeout:
            await asyncio.sleep(5.0)
            waited += 5.0
            status = await client.get(
                f"{BASE_URL}/{model}/requests/{request_id}/status", headers=headers
            )
            state = ""
            if status.status_code < 400:
                try:
                    state = str(status.json().get("status", ""))
                except ValueError:
                    state = status.text[:80]
            print(f"  {waited:5.0f}s  HTTP {status.status_code}  {state}")
            if state.upper() in ("COMPLETED", "OK", "FAILED", "ERROR", "CANCELLED"):
                break
        else:
            print(f"\n  still running after {args.timeout:.0f}s; not an error, just slow.")
            return 0

        result = await client.get(f"{BASE_URL}/{model}/requests/{request_id}", headers=headers)
        print(f"\n  result  HTTP {result.status_code}")
        print(f"          {result.text[:1200]}\n")

    print("  What to check in the result above:")
    print("    * a url ending .mp4 -- the adapter walks the response for one, so")
    print("      any nesting works as long as it is there and ends in a video suffix")
    print("    * whether a duration is reported, which the manifest prefers over")
    print("      the requested length when present")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
