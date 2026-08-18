# Invisible Systems Shorts Factory

A CLI-first pipeline that turns one question — *"ATM은 돈을 어떻게 세는 걸까?"* —
into a rendered 1080x1920 MP4, with sources attached to every factual sentence.

The design it implements is `docs/IMPLEMENTATION_SPEC.md`.

```
Topic → Research → Script → Fact Lock → Scenes → Assets → Narration
      → Subtitles → Manifest → FFmpeg → final.mp4
```

The runtime is a deterministic pipeline, not an agent swarm. An LLM is used at
exactly three points — research, writing, directing — and everything it returns
is validated against a Pydantic schema before the next stage sees it.

## Quick start

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # only needed for real providers

shorts doctor
```

`doctor` checks Python, config, prompts, ffmpeg, the subtitle font, provider
credentials and the project directory. Fix anything it flags before going on.

Out of the box every provider is a mock, so this costs nothing:

```bash
shorts create --topic "ATM은 돈을 어떻게 세는 걸까?" --type inside_object
```

That produces:

```
projects/atmeun-doneul-eotteotge-seneun-geolkka/
├── project.json          canonical state: stages, costs, paths
├── research.json/.md     claims, each citing a source
├── script.json/.txt      narration and beats
├── scenes.json           the shot list
├── prompts/              rendered stage prompts + one file per scene
├── assets/S01/…          source asset and the normalised clip
├── audio/narration.wav
├── subtitles/narration.srt   (.ass alongside it is the burn-in source)
├── manifest.json         final scene timings
├── logs/                 pipeline.jsonl, costs.jsonl, QA reports
└── output/final.mp4
```

## Working on a project

```bash
# Stop before anything expensive and iterate on research/script/scenes for free
shorts create --topic "공항에서 캐리어는 어떻게 내 비행기를 찾아갈까?" \
              --type hidden_system --until direct

# See what would be called and what it would cost, without calling anything
shorts resume projects/<slug> --dry-run

# Human review before spending money
shorts inspect projects/<slug>

# Then the expensive part, one stage at a time
shorts generate projects/<slug>
shorts narrate  projects/<slug>
shorts render   projects/<slug>

shorts status projects/<slug>
shorts resume projects/<slug>     # continues, skipping finished work
```

`--dry-run` is available on every stage command. `--force` re-runs a completed
stage and invalidates everything downstream of it.

## Content types

One engine, three concepts, distinguished by `content_type` and the visual
grammar in `config/content_types.yaml`:

| type | what it shows |
| --- | --- |
| `hidden_system` | infrastructure you never see — sewers, baggage handling, night logistics |
| `inside_object` | the inside of a familiar machine — ATM, escalator, automatic door |
| `behind_action` | what a system does after you press a button — card tap, search, delivery |

## What keeps the output honest

- **Claims, not paragraphs.** Research returns atomic claims, each citing a
  retrieved source by id. Claims whose sources were not actually retrieved are
  dropped before the writer ever sees them.
- **Fact lock.** No paid generation runs until every factual sentence traces to
  a sourced claim. `shorts render` re-checks it.
- **Reality type.** Every scene is `observed`, `reconstructed` or `conceptual`,
  and conceptual scenes are prompted to look diagrammatic so an explanatory
  visualisation is not mistaken for real internal footage.
- **Traceability.** Claim → beat → scene. When a fact turns out to be wrong you
  can find the scenes it touched.

## What keeps the cost down

- **Budget guard.** `config/budgets.yaml` caps total spend, LLM calls, video
  attempts per scene and the number of HIGH-priority scenes. Every paid call
  asks permission first.
- **Idempotency.** An asset is identified by a hash of provider, model, prompt,
  duration and aspect ratio. A completed asset with a matching hash is reused,
  never re-billed.
- **Resume.** State lives in `project.json` and `logs/costs.jsonl`, both written
  atomically. Kill the process at any point and run `shorts resume`.
- **Fallback.** After the configured number of failed video attempts a scene
  becomes a still image with camera motion instead of blocking the edit.

Prices in `config/budgets.yaml` are placeholders. Replace them with your
provider's current official pricing before running anything paid.

## Connecting real providers

Providers are selected in `config/settings.yaml` and credentialed in `.env`:

```yaml
providers:
  llm: openai      # mock | openai
  search: mock     # mock
  image: mock      # mock
  video: mock      # mock
  tts: openai      # mock | openai
```

Implemented today: `openai` for LLM and TTS, mocks for everything. Search, image
and video have interfaces and mocks but no real implementation yet — that is
Phase 5–7 of the spec, and each should be written against the vendor's current
official documentation, one vendor at a time.

## Testing

```bash
pytest                      # unit + mock integration; never touches a paid API
pytest -m "not media"       # skip the tests that need ffmpeg
python scripts/smoke_test.py

ALLOW_LIVE_API_TESTS=1 pytest -m live   # opt-in, costs real money
```

## Requirements

- Python 3.12+
- ffmpeg and ffprobe on `PATH`, built with libass for subtitle burn-in
- A Korean-capable font installed (default: `Noto Sans CJK KR`)
