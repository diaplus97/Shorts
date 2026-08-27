#!/usr/bin/env python3
"""Render one sentence in several voices and paces, then listen and choose.

    python scripts/audition_voices.py
    python scripts/audition_voices.py --voices Kore,Charon,Sulafat --speeds 1.0,1.15
    python scripts/audition_voices.py --text "$(cat some_line.txt)" --speeds 1.2

"The voice is bad and it reads too slowly" is not decidable from a config file,
and re-rendering a whole Short to hear one line costs dollars and twenty
minutes. This buys the same sentence in each candidate for a fraction of a cent
and writes them side by side, so the choice is made by ear.

It also measures **characters per second** for each render. That number is the
one the writer sizes a script against (``script.chars_per_sec``), and it was a
guess until a real voice was measured. Whatever wins here, put its measured rate
in the config or the script length will keep missing the duration target.

Costs whatever the TTS provider charges for a few hundred characters, so cents
at most. The key is read from .env and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from shorts_factory.config import load_config
from shorts_factory.media import is_available, probe, retime
from shorts_factory.providers import build_providers
from shorts_factory.utils import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The opening of the reference Short. Auditioning on the real register matters:
#: a voice that handles a greeting well can still flatten a long declarative
#: sentence full of technical nouns, which is all this pipeline ever writes.
DEFAULT_TEXT = (
    "서울에서 하루 동안 사용하고 버린 물은 네 곳의 물재생센터로 모입니다. "
    "하수의 오염물질은 상당 부분 물에 녹아 있어 단순한 체로는 제거하기 어렵습니다."
)

#: Gemini's prebuilt voices differ more in delivery than in timbre. These are
#: the ones worth hearing first for a documentary read; pass --voices for any
#: other. `python scripts/list_gemini_models.py --kind tts` lists the models,
#: not the voices -- the voice names come from Gemini's speech documentation.
SHORTLIST = ("Kore", "Charon", "Sulafat", "Achernar", "Zephyr", "Iapetus")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voices",
        help=f"Comma-separated voice names. Default: {','.join(SHORTLIST)}",
    )
    parser.add_argument(
        "--speeds",
        default="1.0",
        help="Comma-separated pace multipliers, as in tts.speed. Default: 1.0",
    )
    parser.add_argument("--text", default=DEFAULT_TEXT, help="What to say.")
    parser.add_argument(
        "--out",
        default="projects/_auditions",
        help="Where to write the wav files. Default: projects/_auditions",
    )
    parser.add_argument("--config-dir", type=Path)
    return parser.parse_args()


def parse_speeds(raw: str) -> list[float]:
    speeds: list[float] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = float(chunk)
        except ValueError:
            raise SystemExit(f"FAIL: '{chunk}' is not a number") from None
        if not 0.5 <= value <= 2.0:
            raise SystemExit(f"FAIL: speed {value} is outside the 0.5-2.0 range tts.speed allows")
        speeds.append(value)
    return speeds or [1.0]


def voiced_config(config, voice: str):
    """A copy of the config that asks for one specific voice."""
    tts = config.settings.tts.model_copy(update={"voice": voice})
    settings = config.settings.model_copy(update={"tts": tts})
    return config.model_copy(update={"settings": settings})


async def main() -> int:
    args = parse_args()
    configure_logging("INFO", force=True)

    if not is_available():
        print("FAIL: ffmpeg is not on PATH, and the pace change needs it")
        return 1

    config = load_config(args.config_dir or REPO_ROOT / "config")
    if config.settings.providers.tts == "mock":
        print("FAIL: providers.tts is 'mock'. The mock renders a tone, so there is")
        print("      nothing to audition. Set providers.tts in config/settings.local.yaml.")
        return 1

    voices = [v.strip() for v in (args.voices or ",".join(SHORTLIST)).split(",") if v.strip()]
    speeds = parse_speeds(args.speeds)
    text = args.text.strip()
    if not text:
        print("FAIL: --text is empty")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chars = len(text.replace(" ", ""))

    print()
    print(
        f"  {len(voices)} voice(s) x {len(speeds)} speed(s) = {len(voices) * len(speeds)} renders"
    )
    print(f"  {chars} characters each, model {config.settings.tts.model}")
    print()

    failures = 0
    rows: list[tuple[str, float, float, float]] = []

    for voice in voices:
        provider = build_providers(voiced_config(config, voice)).tts
        for speed in speeds:
            destination = out / f"{voice}__{speed:g}x.wav"
            label = f"{voice} @ {speed:g}x"
            try:
                await provider.synthesize(text, destination)
                if speed != 1.0:
                    await retime(
                        destination,
                        destination,
                        speed=speed,
                        sample_rate=config.settings.tts.sample_rate,
                    )
            # One voice being unavailable should not stop the sweep: the whole
            # point is to find out which ones this key can actually reach.
            except Exception as exc:
                print(f"  {label:<24} FAILED: {type(exc).__name__}: {exc}")
                failures += 1
                continue

            info = probe(destination)
            if info.duration_sec <= 0:
                print(f"  {label:<24} FAILED: rendered a file with no audio")
                failures += 1
                continue
            rate = chars / info.duration_sec
            rows.append((label, info.duration_sec, rate, speed))
            print(
                f"  {label:<24} {info.duration_sec:5.2f}s   {rate:4.1f} chars/sec   {destination}"
            )

    if not rows:
        print("\n  nothing rendered")
        return 1

    configured = config.settings.script.chars_per_sec
    example = rows[0]
    print()
    print(f"  script.chars_per_sec is currently {configured:.1f}")
    print(f"  measured here: {min(r[2] for r in rows):.1f} to {max(r[2] for r in rows):.1f}")
    if failures:
        print(f"  {failures} render(s) failed; the rest are listed above")
    print()
    print("  Listen to the files and pick a pairing by ear, then set all three of")
    print("  these together in config/settings.local.yaml -- shown for the first")
    print("  render as a template, not as a recommendation:")
    print()
    print("    tts:")
    print(f"      voice: {example[0].split(' @ ')[0]}")
    print(f"      speed: {example[3]:g}")
    print("    script:")
    print(f"      chars_per_sec: {example[2]:.1f}")
    print()
    print("  The last line is not optional. The writer sizes a script from")
    print("  chars_per_sec, so leaving it at a guess while the voice reads at a")
    print("  different rate is what makes a 70-second target render at 85.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
