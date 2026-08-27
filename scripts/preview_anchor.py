#!/usr/bin/env python3
"""Buy the one picture the whole Short is drawn from, and nothing else.

    python scripts/preview_anchor.py projects/<slug>

About four cents. It answers the two complaints that no amount of pipeline work
can settle by argument:

* **Is it a diagram or is it footage?** The style was locked after the first
  paid run came out photorealistic in a Short whose reference is a technical
  drawing. This is the picture that decides it.
* **Is it the same machine every cut?** Every scene's opening frame is
  generated from this one, so if this frame is wrong, twelve clips are wrong,
  and finding that out here costs four cents instead of the price of a run.

Run it after `direct` and before `generate`. Nothing else is bought.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from shorts_factory.config import load_config
from shorts_factory.pipeline import build_context, load_existing, require_scenes
from shorts_factory.providers import build_providers
from shorts_factory.stages.asset_generation import ensure_anchor
from shorts_factory.utils import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project directory, e.g. projects/third")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument(
        "--force", action="store_true", help="Buy a new one even if a frame already exists."
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    configure_logging("INFO", force=True)

    config = load_config(args.config_dir or REPO_ROOT / "config")
    if config.settings.providers.image == "mock":
        print("FAIL: providers.image is 'mock', which renders a solid colour.")
        print("      Set it in config/settings.local.yaml first.")
        return 1

    project, workspace = load_existing(args.project, config)
    plan = require_scenes(workspace)
    context = build_context(
        config=config, project=project, workspace=workspace, providers=build_providers(config)
    )
    context.force = args.force

    world = plan.world
    print()
    print(f"  machine   {world.machine_id}")
    print(f"  style     {world.visual_style}")
    print(f"  section   {world.cross_section or '(none declared)'}")
    print(f"  travel    {world.travel_direction or '(none declared)'}")
    for role in world.colour_roles:
        print(f"  colour    {role.as_prompt_fragment()}")
    print()

    prompt = context.providers.prompt_adapter.build_anchor_prompt(plan)
    print("  --- prompt ---")
    print(f"  {prompt}")
    print()

    frame = await ensure_anchor(context, plan)
    if frame is None:
        print("FAIL: video.anchor_frames is false, so there is no anchor to preview.")
        return 1

    print(f"\n  {frame.resolve()}")
    print(f"  spent this run: ${context.tracker.total_usd():.4f}")
    print()
    print("  Open it and ask two questions:")
    print("    1. Does it read as a technical drawing, or as a photograph?")
    print("       Photoreal here means visual_styles.redirect_reality_types is")
    print("       not doing its job, and every scene will inherit it.")
    print("    2. Is the whole machine in frame, laid out the way the narration")
    print("       describes it? Every shot is a closer look at this one picture.")
    print()
    print("  If it is wrong, change config/visual_styles.yaml (anchor_style) or")
    print("  the director's world spec, and run this again. Four cents a try.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
