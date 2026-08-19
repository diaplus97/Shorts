# Invisible Systems Shorts Factory

A CLI-first pipeline that turns one question — *"ATM은 돈을 어떻게 세는 걸까?"* —
into a rendered 1080x1920 MP4, with sources attached to every factual sentence.

The design it implements is `docs/IMPLEMENTATION_SPEC.md`.

```
Topic → Research → Script → Fact Lock → Speech Plan → Scenes → Assets
      → Narration → Subtitles → Manifest → FFmpeg → final.mp4
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

Because every provider is a mock, that produces `output/mock_preview.mp4` with a
burned-in `MOCK PIPELINE` label — never `final.mp4`. `shorts render` refuses to
run until the providers are real; `shorts mock-render` is the explicit
counterpart.

That produces:

```
projects/atmeun-doneul-eotteotge-seneun-geolkka/
├── project.json          canonical state: stages, costs, paths
├── research.json/.md     claims, each citing a source
├── script.json/.txt      narration and beats
├── speech.json           speech units, pauses and delivery
├── speech_timeline.json  measured start/duration per unit
├── scenes.json           the shot list
├── prompts/              rendered stage prompts + one file per scene
├── assets/S01/…          source asset and the normalised clip
├── audio/narration.wav    (units/ holds one wav per speech unit)
├── subtitles/narration.srt   (.ass alongside it is the burn-in source)
├── manifest.json         final scene timings
├── logs/                 pipeline.jsonl, costs.jsonl, QA reports
└── output/final.mp4       (or mock_preview.mp4)
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
shorts speak    projects/<slug>     # free: breaths and pauses, no LLM call
shorts generate projects/<slug>
shorts narrate  projects/<slug>
shorts render   projects/<slug>     # real providers only
shorts mock-render projects/<slug>  # watermarked preview

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

## What keeps the narration listenable

- **One breath, one idea.** The `speak` stage turns the script into
  `SpeechUnit`s — roughly 8–30 characters each — and assigns a pause to every
  break based on why the break is there. It is deterministic: no extra LLM call.
- **Scene cuts land between sentences.** A scene owns whole speech units and its
  narration is rebuilt from them, so a cut through a spoken sentence is
  structurally impossible rather than merely discouraged.
- **Measured timing.** Each unit is synthesised separately and the planned
  pauses are inserted as real silence, so scene lengths and subtitle timings
  come from the audio rather than from proportional guesswork.
- **One narrator.** The channel voice lives in `config/voice.yaml`. Checks catch
  mechanical `~합니다` runs and flat rhythm.

## Sound and captions

- **Scene sound effects.** The director picks a cue per scene from the short
  vocabulary in `config/sfx.yaml`; composition places it at that scene's start
  under the voice. No audio ships here — you supply the files, and a cue with no
  file behind it is a warning, not a failed render. Off by default.
- **One highlighted word.** The writer may mark one word per beat; it is
  coloured in the burned-in caption only. The SRT deliverable stays plain text.
- **Background music** is optional: `shorts render --bgm track.wav` ducks it
  against the narration.

## What keeps the output publishable

- **Mock is never final.** Any mock provider means `mock_preview.mp4` with a
  burned-in label. The encode goes to a staging path and is published only after
  the readiness gate passes.
- **Silence fails the render.** An audio stream is not a voice: mean volume and
  silence ratio are measured, and a dead track blocks the render outright.

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

Implemented today: `openai` for LLM and TTS, `veo` for video, mocks for
everything. Search and image have interfaces and mocks but no real
implementation yet.

### Veo 3

```yaml
providers:
  video: veo
video:
  model: veo-3.0-generate-001    # check the current model id
  allowed_durations: [4, 6, 8]   # required: Veo returns fixed-length clips
  poll_interval_sec: 15
```

with `VIDEO_API_KEY` in `.env` (a Gemini API key). Then:

```bash
shorts resume projects/<slug> --dry-run
```

**Read the cost before running it.** Veo bills per second of generated video,
and a request is rounded up to the next accepted clip length. Eleven scenes is
roughly 60 billed seconds; at the placeholder $0.40/s that is about $21 per
Short, which the default $12 cap will stop part-way through. That is the guard
working. Raise `project.max_total_usd` deliberately, and replace the placeholder
price in `config/budgets.yaml` with the current rate first.

The Veo adapter has not been run against the live API — it is written from the
documented request and response shape, with every drift-prone value in config
(including `extra_parameters` for a field it does not know about). Its request
building and response handling are covered by tests using a mock transport;
whether Google's API matches is covered by `pytest -m live`.

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
