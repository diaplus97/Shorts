#!/usr/bin/env python3
"""Generate exactly one scene with the configured video provider.

    python scripts/try_video_scene.py projects/<slug> [--scene S03] [--yes]

Committing to eleven scenes before you have seen one is how a first paid run
turns into an expensive surprise. This does one, prints what it will cost
first, and reports what came back.

It uses the same code path as `shorts generate` -- the same prompt adapter,
budget guard, poll loop, retry limits and asset ledger -- so a clip produced
here is the clip the full run would have produced.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from shorts_factory.config import load_config
from shorts_factory.domain import AssetType
from shorts_factory.errors import ShortsFactoryError
from shorts_factory.media import is_available, probe
from shorts_factory.pipeline import (
    build_context,
    load_assets,
    load_existing,
    require_scenes,
    save_assets,
)
from shorts_factory.providers import build_providers
from shorts_factory.stages.asset_generation import generate_scene, requested_video_seconds
from shorts_factory.utils import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project directory or slug.")
    parser.add_argument("--scene", help="Scene id. Defaults to the first video scene.")
    parser.add_argument("--config-dir", default=None, help="Directory of YAML config files.")
    parser.add_argument("--yes", action="store_true", help="Skip the cost confirmation.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    configure_logging("INFO", force=True)
    if not is_available():
        print("FAIL: ffmpeg/ffprobe not found on PATH")
        return 1

    config = load_config(args.config_dir or REPO_ROOT / "config")
    project, workspace = load_existing(args.project, config)
    context = build_context(
        config=config,
        project=project,
        workspace=workspace,
        providers=build_providers(config),
    )

    plan = require_scenes(workspace)
    if args.scene:
        scene = plan.scene_by_id(args.scene)
        if scene is None:
            print(f"FAIL: no scene {args.scene} in {workspace.scenes_json}")
            return 1
    else:
        scene = next((s for s in plan.scenes if s.asset_type is AssetType.VIDEO), None)
        if scene is None:
            print("FAIL: this plan has no video scenes")
            return 1

    video = context.providers.video
    adapter = context.providers.prompt_adapter
    seconds = requested_video_seconds(context, scene)
    estimate = context.guard.estimate_video_usd(video.name, seconds, video.model)

    print()
    print(f"  project   : {workspace.root}")
    print(f"  scene     : {scene.id} ({scene.priority}, {scene.reality_type})")
    print(f"  provider  : {video.name} / {video.model}")
    print(f"  planned   : {scene.duration_sec:.2f}s -> billed as {seconds:g}s")
    print(f"  estimate  : ${estimate:.4f}")
    print(f"  budget    : ${context.guard.remaining_usd:.4f} remaining")
    print()
    print("  prompt    :")
    print(f"    {adapter.build_prompt(scene, plan)}")
    print("  negative  :")
    print(f"    {adapter.build_negative_prompt(scene)}")
    print()

    if not args.yes and not video.is_mock:
        answer = input(f"Spend about ${estimate:.4f} on one clip? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("cancelled; nothing was called")
            return 0

    ledger = load_assets(workspace)
    try:
        record = await generate_scene(context, scene, ledger, plan)
    except ShortsFactoryError as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        return 1

    ledger.put(record)
    save_assets(workspace, ledger)

    source = workspace.root / record.local_path
    info = probe(source)
    print()
    print("  RESULT")
    print(f"    status    : {record.status}")
    print(f"    fallback  : {record.fallback_used}")
    print(f"    file      : {source}")
    print(
        f"    media     : {info.width}x{info.height}, {info.duration_sec:.2f}s, {info.video_codec}"
    )
    print(f"    audio     : {'present (stripped at normalisation)' if info.has_audio else 'none'}")
    print(f"    billed    : ${context.tracker.total_for('video'):.4f}")
    if info.width and info.height:
        ratio = info.width / info.height
        expected = context.settings.output.width / context.settings.output.height
        if abs(ratio - expected) > 0.01:
            print(
                f"    WARNING   : aspect {ratio:.4f}, expected {expected:.4f} — check aspectRatio"
            )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
