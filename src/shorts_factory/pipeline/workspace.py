"""Project directory layout (spec section 5.1).

Everything a run produces lives under one directory, so a project can be
inspected, resumed, archived or deleted as a unit.
"""

from __future__ import annotations

from pathlib import Path

from ..utils import ensure_dir


class ProjectWorkspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    # -- top level files -------------------------------------------------

    @property
    def project_json(self) -> Path:
        return self.root / "project.json"

    @property
    def research_json(self) -> Path:
        return self.root / "research.json"

    @property
    def research_md(self) -> Path:
        return self.root / "research.md"

    @property
    def script_json(self) -> Path:
        return self.root / "script.json"

    @property
    def script_txt(self) -> Path:
        return self.root / "script.txt"

    @property
    def speech_json(self) -> Path:
        return self.root / "speech.json"

    @property
    def speech_timeline_json(self) -> Path:
        """Measured unit timings, written after the voice track exists."""
        return self.root / "speech_timeline.json"

    @property
    def scenes_json(self) -> Path:
        return self.root / "scenes.json"

    @property
    def assets_json(self) -> Path:
        return self.root / "assets.json"

    @property
    def manifest_json(self) -> Path:
        return self.root / "manifest.json"

    # -- directories -----------------------------------------------------

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def scene_prompts_dir(self) -> Path:
        return self.prompts_dir / "scenes"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def subtitles_dir(self) -> Path:
        return self.root / "subtitles"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def work_dir(self) -> Path:
        """Scratch space for intermediate render artefacts."""
        return self.root / ".work"

    # -- named artefacts -------------------------------------------------

    @property
    def narration_wav(self) -> Path:
        return self.audio_dir / "narration.wav"

    @property
    def unit_audio_dir(self) -> Path:
        """One wav per speech unit, kept so a re-render need not re-synthesise."""
        return self.audio_dir / "units"

    def unit_audio(self, unit_id: str) -> Path:
        return self.unit_audio_dir / f"{unit_id}.wav"

    @property
    def narration_meta(self) -> Path:
        return self.audio_dir / "narration.meta.json"

    @property
    def narration_srt(self) -> Path:
        return self.subtitles_dir / "narration.srt"

    @property
    def narration_ass(self) -> Path:
        """Burn-in source. narration.srt stays the deliverable."""
        return self.subtitles_dir / "narration.ass"

    @property
    def final_video(self) -> Path:
        """The production deliverable. Only a run with no mock provider may write it."""
        return self.output_dir / "final.mp4"

    @property
    def mock_preview(self) -> Path:
        """What a run containing any stand-in produces instead (spec v0.2 section 5.3)."""
        return self.output_dir / "mock_preview.mp4"

    def output_video(self, *, production_ready: bool) -> Path:
        return self.final_video if production_ready else self.mock_preview

    @property
    def cost_ledger(self) -> Path:
        return self.logs_dir / "costs.jsonl"

    @property
    def pipeline_log(self) -> Path:
        return self.logs_dir / "pipeline.jsonl"

    def scene_dir(self, scene_id: str) -> Path:
        return self.assets_dir / scene_id

    def scene_clip(self, scene_id: str) -> Path:
        return self.scene_dir(scene_id) / "final.mp4"

    def scene_prompt_file(self, scene_id: str) -> Path:
        return self.scene_prompts_dir / f"{scene_id}.txt"

    def stage_prompt_file(self, stage: str) -> Path:
        return self.prompts_dir / f"{stage}.user.md"

    def ensure(self) -> ProjectWorkspace:
        for directory in (
            self.root,
            self.prompts_dir,
            self.scene_prompts_dir,
            self.assets_dir,
            self.audio_dir,
            self.unit_audio_dir,
            self.subtitles_dir,
            self.logs_dir,
            self.output_dir,
            self.work_dir,
        ):
            ensure_dir(directory)
        return self

    def exists(self) -> bool:
        return self.project_json.exists()
