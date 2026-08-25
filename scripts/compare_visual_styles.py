#!/usr/bin/env python3
"""See what each visual-style position actually orders, and optionally buy it.

    python scripts/compare_visual_styles.py projects/<slug> --scene S03
    python scripts/compare_visual_styles.py projects/<slug> --scene S03 --generate

Whether a machine interior should be rendered as footage or as a drawing is an
editorial identity choice, not a bug, and it is not decidable from prose. This
prints the three positions' prompts side by side for free, and with --generate
buys one clip of each so the difference can be looked at rather than argued.

The positions:

    photoreal       every scene photorealistic. What shipped before, and what
                    makes an unverified interior look like documentary evidence.
    reconstruction  observed scenes photoreal, interiors as engineering
                    cutaways, abstractions as flat diagrams. The default.
    diagram         nothing photorealistic. Furthest from being mistaken for
                    footage, and furthest from looking like a real place.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from shorts_factory.config import Realism, RealityTypeStyle, load_config
from shorts_factory.domain import AssetType, RealityType
from shorts_factory.media import is_available, probe
from shorts_factory.pipeline import build_context, load_existing, require_scenes
from shorts_factory.providers import build_providers
from shorts_factory.providers.video.prompt_adapter import GenericPromptAdapter
from shorts_factory.stages.asset_generation import requested_video_seconds
from shorts_factory.utils import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[1]

PHOTOREAL = Realism(photorealistic=True, physically_plausible=True)
DRAWN = Realism(photorealistic=False, physically_plausible=True)
FLAT = Realism(photorealistic=False, physically_plausible=False)

AS_FOOTAGE = "shot as real-world documentary footage"
AS_CUTAWAY = (
    "technical cutaway reconstruction, engineering-accurate proportions, clean "
    "sectional view, matte surfaces, no photographic depth of field, visibly a "
    "drawing rather than footage"
)
AS_DIAGRAM = (
    "explanatory diagrammatic visualisation, flat graphic treatment, limited "
    "palette, clearly stylised so it is not mistaken for real internal footage"
)


def style(realism: Realism, suffix: str) -> RealityTypeStyle:
    return RealityTypeStyle(realism=realism, suffix=suffix)


#: Each position sets the realism flag **and** the suffix together. Setting only
#: the flag produces a prompt that says "visibly a drawing rather than footage,
#: ... photorealistic" -- a contradiction, and an expensive one to generate.
POSITIONS: dict[str, dict[str, RealityTypeStyle]] = {
    "photoreal": {
        "observed": style(PHOTOREAL, AS_FOOTAGE),
        "reconstructed": style(PHOTOREAL, AS_FOOTAGE),
        "conceptual": style(PHOTOREAL, AS_FOOTAGE),
    },
    "reconstruction": {
        "observed": style(PHOTOREAL, AS_FOOTAGE),
        "reconstructed": style(DRAWN, AS_CUTAWAY),
        "conceptual": style(FLAT, AS_DIAGRAM),
    },
    "diagram": {
        "observed": style(DRAWN, AS_CUTAWAY),
        "reconstructed": style(FLAT, AS_DIAGRAM),
        "conceptual": style(FLAT, AS_DIAGRAM),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project directory or slug.")
    parser.add_argument("--scene", help="Scene id. Defaults to the first video scene.")
    parser.add_argument("--config-dir", default=None)
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Actually buy one clip per position. Costs real money; prints the "
        "total and asks first.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the cost confirmation.")
    parser.add_argument(
        "--out", default="style-comparison", help="Directory for the generated clips."
    )
    return parser.parse_args()


def styled_config(config, position: str):
    """A copy of the config with one position's look applied."""
    styles = config.visual_styles.model_copy(deep=True)
    for reality_type, entry in POSITIONS[position].items():
        styles.reality_type_style[reality_type] = entry
    return config.model_copy(update={"visual_styles": styles})


async def main() -> int:
    args = parse_args()
    configure_logging("INFO", force=True)

    config = load_config(args.config_dir or REPO_ROOT / "config")
    project, workspace = load_existing(args.project, config)
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

    print()
    print(f"  scene     : {scene.id} ({scene.purpose}, reality_type={scene.reality_type.value})")
    print(f"  subject   : {scene.visual_subject}")
    print()
    if scene.reality_type is RealityType.OBSERVED:
        print("  NOTE: this scene is 'observed', so photoreal and reconstruction agree on")
        print("        it. Pick a 'reconstructed' scene to see them differ.")
        print()

    prompts: dict[str, str] = {}
    for position in POSITIONS:
        adapter = GenericPromptAdapter(styled_config(config, position).visual_styles)
        prompts[position] = adapter.build_prompt(scene, plan)
        print(f"  --- {position} " + "-" * (66 - len(position)))
        print(f"    {prompts[position]}")
        print()

    identical = [
        (a, b)
        for index, a in enumerate(POSITIONS)
        for b in list(POSITIONS)[index + 1 :]
        if prompts[a] == prompts[b]
    ]
    for a, b in identical:
        print(f"  NOTE: '{a}' and '{b}' order the identical prompt for this scene.")
        print("        They differ on other reality types; generating both would pay twice.")
    if identical:
        print()

    if not args.generate:
        print("  Prompts only. Add --generate to buy one clip of each and look at them.")
        return 0

    if not is_available():
        print("FAIL: ffmpeg/ffprobe not found on PATH")
        return 1

    context = build_context(
        config=config, project=project, workspace=workspace, providers=build_providers(config)
    )
    video = context.providers.video
    seconds = requested_video_seconds(context, scene)
    each = context.guard.estimate_video_usd(video.name, seconds, video.model)
    # Only pay once per distinct prompt.
    distinct = list(
        dict.fromkeys(min(k for k in prompts if prompts[k] == v) for v in prompts.values())
    )
    total = each * len(distinct)

    print(f"  provider  : {video.name} / {video.model}")
    print(f"  {len(distinct)} clips x {seconds:g}s x ${each:.4f} = ${total:.4f}")
    print(f"  budget    : ${context.guard.remaining_usd:.4f} remaining")
    print()
    if not args.yes and not video.is_mock:
        answer = input(f"Spend about ${total:.4f} on {len(distinct)} clips? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("cancelled; nothing was called")
            return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for position in distinct:
        destination = out / f"{scene.id}-{position}.mp4"
        print(f"\n  generating {position} ...")
        try:
            job = await video.submit(
                prompt=prompts[position],
                duration_sec=seconds,
                aspect_ratio=config.settings.video.aspect_ratio,
                negative_prompt=adapter.build_negative_prompt(scene) or None,
            )
            while True:
                state = await video.status(job)
                if state.state == "completed":
                    break
                if state.state == "failed":
                    raise RuntimeError(state.error or "no reason given")
                await asyncio.sleep(config.settings.video.poll_interval_sec)
            result = await video.download(job, destination)
        except Exception as exc:
            print(f"    FAILED: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        info = probe(result.path)
        print(f"    {result.path}  {info.width}x{info.height}, {info.duration_sec:.2f}s")

    print(f"\n  clips in {out.resolve()}")
    print("  Watch them next to each other and pick one. Then set the winner in")
    print("  config/visual_styles.local.yaml, or edit config/visual_styles.yaml to")
    print("  change the house style for good.")
    return 1 if failures == len(distinct) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
