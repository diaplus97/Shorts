#!/usr/bin/env python3
"""End-to-end smoke test with mock providers.

    python scripts/smoke_test.py

Builds one complete Short in a temporary directory and checks the result with
ffprobe. No paid API is contacted. Exits non-zero on any problem.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from shorts_factory.config import load_config
from shorts_factory.domain import ContentType, PipelineState
from shorts_factory.media import is_available, probe
from shorts_factory.pipeline import build_context, create_project, run_pipeline
from shorts_factory.providers import build_providers
from shorts_factory.utils import configure_logging, read_json

REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC = "ATM은 돈을 어떻게 세는 걸까?"


async def main() -> int:
    configure_logging("INFO", force=True)
    if not is_available():
        print("FAIL: ffmpeg/ffprobe not found on PATH")
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="shorts-smoke-"))
    try:
        config = load_config(REPO_ROOT / "config")
        config.settings.project_root = str(workdir / "projects")
        config.settings.providers.llm = "mock"
        config.settings.providers.search = "mock"
        config.settings.providers.image = "mock"
        config.settings.providers.video = "mock"
        config.settings.providers.tts = "mock"
        config.settings.video.poll_interval_sec = 0.01

        project, workspace = create_project(
            topic=TOPIC, content_type=ContentType.INSIDE_OBJECT, config=config
        )
        context = build_context(
            config=config,
            project=project,
            workspace=workspace,
            providers=build_providers(config),
        )
        result = await run_pipeline(context)

        problems: list[str] = []
        if result.state is not PipelineState.DONE:
            problems.append(f"pipeline ended in state {result.state}")

        # Every provider here is a mock, so the run must produce a watermarked
        # preview and must never produce final.mp4.
        output = workspace.mock_preview
        if workspace.final_video.exists():
            problems.append("a mock run produced final.mp4")
        if not output.exists():
            problems.append("mock_preview.mp4 was not produced")
        else:
            info = probe(output)
            if (info.width, info.height) != (1080, 1920):
                problems.append(f"resolution {info.width}x{info.height}, expected 1080x1920")
            if not info.has_audio:
                problems.append("final.mp4 has no audio stream")
            if not 45.0 <= info.duration_sec <= 70.0:
                problems.append(f"duration {info.duration_sec:.1f}s is outside 45-70s")

        for name, path in (
            ("research.json", workspace.research_json),
            ("script.json", workspace.script_json),
            ("scenes.json", workspace.scenes_json),
            ("manifest.json", workspace.manifest_json),
            ("narration.srt", workspace.narration_srt),
            ("speech.json", workspace.speech_json),
            ("speech_timeline.json", workspace.speech_timeline_json),
        ):
            if not path.exists():
                problems.append(f"{name} is missing")

        if problems:
            print("\nSMOKE TEST FAILED")
            for problem in problems:
                print(f"  - {problem}")
            return 1

        info = probe(output)
        speech = read_json(workspace.speech_json)
        print("\nSMOKE TEST PASSED")
        print(f"  output   : {output}")
        print(f"  duration : {info.duration_sec:.2f}s at {info.width}x{info.height}")
        print(f"  speech   : {len(speech['units'])} units")
        print(context.tracker.render_table())
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
