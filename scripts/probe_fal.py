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
import sys

import httpx
from dotenv import load_dotenv

from shorts_factory.providers.base import find_secret
from shorts_factory.providers.video.fal import queue_app_id

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


#: Config keys that switch a request field off, for the ones this pipeline
#: knows how to stop sending.
_FIELD_SETTING = {"duration": "duration_field", "aspect_ratio": "aspect_ratio_field"}


def rejected_field(message: str, sent: dict) -> str | None:
    """The field fal refused, when the message names one it can be sent without.

    Matched on the value as well as the name: Veo taught this pipeline that a
    400 often names what was wrong rather than which key held it -- "1080p is
    not supported for a duration of 6 seconds" names neither `resolution` nor
    `duration` -- and eight scenes were lost to reading only the key names.
    """
    lowered = message.lower()
    for field in _FIELD_SETTING:
        if field not in sent:
            continue
        if field in lowered:
            return field
        value = str(sent[field]).strip().lower()
        if len(value) > 2 and not value.isdigit() and value in lowered:
            return field
    return None


async def submit_dropping_rejected(client, model, headers, payload):
    """POST, dropping any optional field fal refuses, until it takes one.

    Free to do: a 400 is refused before generation starts, so every attempt
    that fails costs nothing. Only the attempt that succeeds is billed, and
    there is exactly one of those.
    """
    attempted = dict(payload)
    dropped: list[str] = []
    while True:
        response = await client.post(f"{BASE_URL}/{model}", headers=headers, json=attempted)
        if response.status_code < 400:
            return response, attempted, dropped
        field = rejected_field(response.text, attempted)
        if field is None:
            return response, attempted, dropped
        attempted.pop(field)
        dropped.append(field)
        print(f"  refused '{field}' (free -- nothing generated); retrying without it")


def config_lines(model: str, payload: dict, dropped: list[str]) -> str:
    """The settings.local.yaml block matching the shape that worked."""
    lines = ["video:", f"  model: {model}"]
    for field, setting in _FIELD_SETTING.items():
        if field in dropped:
            lines.append(f"  {setting}: null")
    if isinstance(payload.get("duration"), str):
        lines.append("  duration_as_string: true")
    return "\n".join("    " + line for line in lines)


async def main() -> int:
    args = parse_args()
    load_dotenv(override=False)
    # find_secret, not os.environ, so the aliases the providers accept are the
    # same ones this accepts. Reading the canonical name directly is how this
    # ended up reporting that FAL_KEY was missing while printing "did you mean
    # FAL_API_KEY?" about a key that was sitting right there and would have
    # worked in a real run.
    found = find_secret("FAL_KEY")
    if found is None:
        from shorts_factory.scripts_doctor import _suggest_similar

        print("FAIL: no fal key found.")
        _suggest_similar("FAL_KEY")
        print("\n  To copy it in from another .env on this machine:")
        print("    ./run.sh --find-key")
        return 1
    key_name, key = found
    if key_name != "FAL_KEY":
        print(f"  using {key_name}")

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
        response, payload, dropped = await submit_dropping_rejected(client, model, headers, payload)
        print(f"  submit  HTTP {response.status_code}")
        print(f"          {response.text[:600]}\n")
        if response.status_code >= 400:
            print("  Nothing was billed: a 400 is refused before generation starts.")
            print("  The message above names what fal did not accept, and dropping")
            print("  fields one at a time did not find a shape it would take.")
            return 1
        if dropped:
            print(f"  These fields were refused and left out: {', '.join(dropped)}")
            print("  Put that in config/settings.local.yaml so a real run sends the")
            print("  same shape:\n")
            print(config_lines(model, payload, dropped))
            print()

        submitted = response.json()
        request_id = submitted.get("request_id")
        if not request_id:
            print("  FAIL: no request_id in the reply, so there is nothing to poll.")
            return 1

        # fal's queue does not live under the model path: submitting to
        # fal-ai/wan/v2.6/image-to-video returns a status_url under fal-ai/wan.
        # Building the url from the model gets 405 on every poll, which looks
        # like a stuck job. The reply says where to look.
        status_url = submitted.get("status_url") or (
            f"{BASE_URL}/{queue_app_id(model)}/requests/{request_id}/status"
        )
        result_url = submitted.get("response_url") or (
            f"{BASE_URL}/{queue_app_id(model)}/requests/{request_id}"
        )
        print(f"  polling {status_url}\n")

        waited = 0.0
        while waited < args.timeout:
            await asyncio.sleep(5.0)
            waited += 5.0
            status = await client.get(status_url, headers=headers)
            state = ""
            if status.status_code < 400:
                try:
                    state = str(status.json().get("status", ""))
                except ValueError:
                    state = status.text[:80]
            print(f"  {waited:5.0f}s  HTTP {status.status_code}  {state}")
            if state.upper() in ("COMPLETED", "OK", "FAILED", "ERROR", "CANCELLED"):
                # The whole body, not just the word. A job that "completed" in
                # five seconds did not generate a video -- Wan takes minutes --
                # and whatever it did instead is described here.
                print(f"\n  status body\n          {status.text[:1500]}\n")
                break
        else:
            print(f"\n  still running after {args.timeout:.0f}s; not an error, just slow.")
            return 0

        # One url, matching fal's own client: the queue answers under
        # owner/alias. A 404 naming a path here is not "look elsewhere" -- it
        # is fal saying the endpoint the request was submitted to does not
        # exist, which is also why the job "completed" in seconds.
        result = await client.get(result_url, headers=headers)
        print(f"\n  result  HTTP {result.status_code}  {result_url}")
        print(f"          {result.text[:1200]}\n")
        if result.status_code >= 400:
            if "not found" in result.text.lower() and "path" in result.text.lower():
                print(f"  fal has no endpoint '{model}'.")
                print("  A submission to any path under a real app is accepted, so a wrong")
                print("  id is not refused -- it queues, finishes in seconds having made")
                print("  nothing, and only fails here. Get the exact id from the model's")
                print("  page at fal.ai/models (the API tab) and try it:")
                print("      ./run.sh --probe --model <id>")
            else:
                print("  the clip was generated and billed but could not be collected.")
            return 1

    print("  What to check in the result above:")
    print("    * a url ending .mp4 -- the adapter walks the response for one, so")
    print("      any nesting works as long as it is there and ends in a video suffix")
    print("    * whether a duration is reported, which the manifest prefers over")
    print("      the requested length when present")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
