# AGENTS.md

## Project

This repository implements a CLI-first AI Shorts production pipeline.

The MVP converts one topic into a locally rendered 9:16 MP4. The canonical
design document is `docs/IMPLEMENTATION_SPEC.md`.

## Architecture Rules

- Use Python 3.12.
- Keep the runtime deterministic. The pipeline is an ordered list of stages,
  not an agent swarm.
- Do not introduce multi-agent frameworks (LangGraph, CrewAI, AutoGen, or
  equivalents).
- All LLM outputs must be validated by Pydantic before they reach another stage.
- External APIs must be accessed through the provider interfaces in
  `src/shorts_factory/providers/base.py`. Domain and stage code never imports
  an SDK or builds a URL.
- Do not call paid APIs in normal tests. `tests/conftest.py` sets
  `SHORTS_BLOCK_LIVE_API=1`; live tests need `ALLOW_LIVE_API_TESTS=1` and
  `pytest -m live`.
- Do not implement upload automation during the MVP.
- `project.json` is the canonical project state. Every stage reads it, updates
  it, and writes it atomically.
- Every expensive pipeline stage must be resumable and idempotent. Re-running a
  stage invalidates every stage after it.
- Video generation must respect the budget guard in `config/budgets.yaml`.
  Prices are configuration, never constants in Python.
- Do not silently discard failed scenes. A scene that cannot be generated falls
  back to a still image with camera motion, and the fallback is recorded.
- Separate observed / reconstructed / conceptual visuals. An explanatory
  visualisation must never be labelled `observed`.
- A run containing any mock provider is not production. It writes
  `output/mock_preview.mp4` with a burned-in label, never `final.mp4`. Encode to
  a staging path and publish only after the readiness gate passes.
- An audio stream is not a voice. A silent or near-silent track fails the render
  for mock and production runs alike.
- `SpeechPlan` decides how the narration is broken into breaths. Scenes hold
  whole speech units and derive their narration from them, so a cut can never
  land mid-sentence.
- Speech planning is a deterministic stage, not an LLM call and not an agent.
- Provider-specific TTS syntax never enters the domain model. It lives in the
  TTS adapter.
- No audio or media assets are committed. A configured sound effect with no file
  behind it warns and is skipped; it never fails a render.
- Do not leave a schema field that nothing reads or writes. Either wire it up or
  delete it.
- Do not expand the scope without an explicit requirement.

## Layout

```
src/shorts_factory/
  domain/     Pydantic models. No I/O.
  pipeline/   Orchestrator, project state, checkpoints, workspace layout.
  stages/     One module per stage. Ordinary functions.
  providers/  Protocols plus one implementation per kind.
  media/      ffmpeg/ffprobe wrappers, normalisation, audio QA, subtitles, composition.
  quality/    Structural, factual and technical checks.
  cost/       Cost ledger and budget guard.
  quality/    Includes the content and speech contracts, and the readiness gate.
  utils/      Small helpers with no package dependencies.
```

Side effects stay separated: domain logic, file I/O, network I/O and media
processing live in different modules.

## Verification Commands

- `ruff check .`
- `ruff format --check .`
- `mypy`
- `pytest`
- `python -m shorts_factory doctor`
- `python scripts/smoke_test.py`

## Definition of Done

A task is not complete until:

1. relevant tests pass,
2. lint passes,
3. documentation is updated when behaviour changes,
4. no secrets are committed.
