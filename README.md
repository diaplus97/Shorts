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


## Where this stands

Last commit `b033670`, 2026-08-26. Read this before changing anything: most of
what is written here was paid for, and rediscovering it costs money or a wasted
run.

### What has actually run against a real API

One complete paid run has happened, producing a real `final.mp4` at $2.97 with
genuine sources. What that exercised, and what it did not:

| | state | evidence |
|---|---|---|
| LLM (Gemini) | **works** | wrote scripts across several runs |
| Search (Gemini grounding) | **works** | real sources: 효성TNS, ECB, Bank of Greece, a patent, arXiv |
| TTS (Gemini) | **works, sounds wrong** | audio renders; the read is too slow and the voice was rejected |
| Image (Gemini) | **works** | generated the stills 8 of 10 scenes fell back to |
| Veo 3.1 | **works, mostly refused** | 2 clips of 10; the other 8 hit a parameter rejection |
| fal.ai | **submit verified, rest not** | HTTP 200 + request_id; polling was broken and the fix is untested |
| ffmpeg composition | **works** | produced the finished MP4 |

Every provider docstring saying "not yet run against the live API" predates
that run. Only the fal one is still true end to end.

**The last thing that happened:** the fal probe submitted successfully and then
405'd on every poll, because fal's queue lives under the base app id
(`fal-ai/wan`) and not the model path (`fal-ai/wan/v2.6/image-to-video`). Fixed
in `b033670` by following the `status_url` the submit reply returns. **That fix
has not been run.** One clip was generated and billed during that probe and
never collected.

### The traps already paid for

Each of these cost money or a failed run to find. They are in the code with
comments; this is the index.

| Trap | Where |
|---|---|
| fal's queue is under `fal-ai/wan`, not the versioned model path — otherwise 405 forever | `providers/video/fal.py` |
| Gemini TTS returns headerless PCM; saving it as .wav gives a file with no stream | `providers/tts/gemini.py` |
| No `imagen-*` model exists on these keys — the image models are `gemini-*-image` on `generateContent`, not `:predict` | `providers/image/gemini.py` |
| A Veo 400 names the offending *value*, not the field: "1080p is not supported for a duration of 6 seconds". Reading key names only cost 8 of 10 scenes | `providers/video/veo.py` |
| Gemini's schema subset rejects `$ref`/`$defs`; filtering keywords *inside* `properties` silently deleted ScriptResult's `title` field | `providers/llm/gemini.py` |
| A spending-cap 429 is an account setting, not congestion — retrying it four times only delays the message | `providers/base.py` |
| Common static ffmpeg builds have no `drawtext` (no libfreetype), so the mock watermark degrades to `drawbox` | `media/compose.py` |
| tenacity clears `retry_state.outcome` before yielding, so a retry reason has to be recorded on the way past | `providers/base.py` |
| `grep -c` prints 0 *and* exits 1, so `|| echo 0` yields the string "0\n0" | `scripts/import_key.sh` |
| `python` is not a command on stock Ubuntu/WSL, and `python3` is not this project's interpreter | `run.sh` |

### What is known to be wrong

Ranked by how much it hurts the output, from the reviews of the one finished
video:

1. **The script explains too little.** Structural gates all pass — seven beats,
   sourced claims, the arc in order — and a reader still cannot picture the
   mechanism. Gates were the wrong tool: `quality/` is 1,584 lines and 30
   checks, and every one of them passed the script that was judged worse than
   asking an LLM the bare question. What moved the needle both times was the
   writer prompt, which is 560 lines against 13,000 lines of machinery.
2. **Cost.** Veo 3.1 Standard at $0.40/s prices a 65-second Short at about $26,
   and it was the default. `providers.video: fal` with Wan 2.6 is $3.25 for the
   same Short. This is configured in the example override but has never
   completed a run.
3. **Every cut redesigned the machine.** Addressed by the anchor frame — one
   still per Short, every scene's opening frame generated from it, that frame
   handed to the video model — but not yet seen in a finished video.
4. **Everything came out photorealistic.** The diagram styles were correct all
   along; the director labelled every scene `observed` despite the prompt
   telling it not to, and nothing checked. `redirect_reality_types` now draws
   `observed` as a cutaway. Not yet seen in a finished video.
5. **TTS pace and voice.** `tts.speed` retimes the rendered audio and
   `scripts/audition_voices.py` renders one line in several voices for a
   fraction of a cent. Neither has been used in anger.

### If you are picking this up

Run it where you can see it fail. This repository was built from a remote
container with no access to the author's filesystem, no reachable fal.ai
documentation, and no ability to make a paid call — so five consecutive rounds
were spent on integration bugs that one local run would have caught in a
minute each. The single highest-value change to how this is worked on is to
work on it locally.

The next concrete step is one command:

```bash
./run.sh --probe
```

It submits one clip, follows the queue url, and prints the raw response. If it
completes, `./run.sh "<topic>"` is a $3-5 full run. If it fails, the message
names the field and the probe prints the config block that fixes it.


## Running it

One command, from a cold terminal:

```bash
./run.sh "ATM은 어떻게 지폐를 셀까?"
```

It pulls, creates the virtualenv, installs, checks the environment and runs.
Other modes:

```bash
./run.sh --probe                    # one cheap fal call to check the API shape
./run.sh --doctor                   # environment check only
./run.sh --script-only "<topic>"    # stop before anything is billed
./run.sh --resume <project>         # continue where a run stopped
```

Every command below that starts with `.venv/bin/python` is written that way on
purpose. `python` is not a command on a stock Ubuntu or WSL install -- only
`python3` is -- and `python3` is not the interpreter this project's
dependencies are installed into. `run.sh` avoids the question entirely.

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

## One command

```bash
shorts create --topic "ATM은 돈을 어떻게 세는 걸까?" --type inside_object
```

That runs every stage: research, write, fact lock, speech plan, direct,
generate, narrate, validate, compose. It stops once, before the first stage
that spends money on assets, to print the script and ask:

```
  SCRIPT
    ATM은 지폐를 어떻게 한 장씩 셀까요?

    [hook      ] ATM은 지폐를 어떻게 한 장씩 셀까요?
    [reveal    ] 지폐를 넣으면 안에서는 바로 확인이 시작됩니다. …

  spent so far $0.2100 — the stages after this cost about $6.6000 more

  Generate the video from this script? [y/N]:
```

Answer `n` and the run stops with everything already done left on disk;
`shorts resume <slug>` picks up from there. Reading the narration before
eleven clips are bought against it is the cheapest quality control available,
because a script nobody read is not rescued by good pictures.

`--yes` skips the question for unattended runs, and `--until direct` is
already a decision not to spend.

## Connecting real providers

Providers are selected in config and credentialed in `.env`. The committed
`config/settings.yaml` stays on mocks so a fresh checkout cannot spend money by
accident, so put your own choices in a **local override** instead of editing it:

```bash
```

`config/*.local.yaml` is gitignored and merged over the matching `*.yaml` at
load time. Nested keys merge, so name only what you change; lists replace
wholesale. Editing `settings.yaml` directly works too, but every `git pull`
then collides with it, and the usual way out of that collision is to discard
your edits and silently fall back to mock.

```yaml
# config/settings.local.yaml
providers:
  llm: openai
  video: veo
  tts: openai

video:
  model: veo-3.1-fast-generate-preview
  allowed_durations: [4, 6, 8]
  poll_interval_sec: 15
```

`shorts doctor` lists any override in effect, because running against settings
that do not appear in `git diff` is worth stating out loud.

Implemented today: `openai` for LLM and TTS, `veo` for video, mocks for
everything. Search and image have interfaces and mocks but no real
implementation yet.

### Veo 3

```yaml
providers:
  video: veo
video:
  model: veo-3.1-fast-generate-preview
  allowed_durations: [4, 6, 8]   # required: Veo returns fixed-length clips
  poll_interval_sec: 15
```

with `VIDEO_API_KEY` in `.env` (a Gemini API key). Then:

```bash
shorts resume projects/<slug> --dry-run
```

**Veo 3 is gone.** `veo-3.0-generate-001`, `veo-3.0-fast-generate-001` and
Veo 2 were shut down on 2026-06-30; the config refuses those ids rather than
letting you find out through a 404 mid-run. Use a Veo 3.1 id.

**Read the cost before running it.** Veo bills per second, and a request is
rounded up to the next accepted clip length, so eleven scenes is roughly 60
billed seconds (rates checked 2026-08-19):

| model | rate | one Short |
| --- | --- | --- |
| `veo-3.1-generate-preview` (Standard) | $0.40/s | ~$24 |
| `veo-3.1-fast-generate-preview` (Fast) | $0.15/s | ~$9 |

plus up to two retries per failed scene. The default $12 cap fits Fast and
deliberately does not fit Standard — raise `project.max_total_usd` consciously
after a dry run rather than discovering it mid-render. Prices move; re-check
before a paid run.

The Veo adapter has not been run against the live API — it is written from the
documented request and response shape, with every drift-prone value in config
(including `extra_parameters` for a field it does not know about). Its request
building and response handling are covered by tests using a mock transport;
whether Google's API matches is covered by `pytest -m live`.

## Testing

```bash
pytest                      # unit + mock integration; never touches a paid API
pytest -m "not media"       # skip the tests that need ffmpeg
.venv/bin/python scripts/smoke_test.py

ALLOW_LIVE_API_TESTS=1 pytest -m live   # opt-in, costs real money
```

## Setting up on Windows

`run.sh` is bash. Git Bash ships with Git for Windows and runs it unchanged, so
that is the shorter path; PowerShell needs the underlying commands instead.

Check first whether the machine already has a clone. `C:\Users\<you>\Shorts\Shorts`
is where an earlier one was found:

```bash
cd /c/Users/SAMSUNG/Shorts/Shorts && git remote -v
```

If that prints `diaplus97/Shorts`, skip the clone and just `git pull`.

### Git Bash

```bash
cd /c/Users/SAMSUNG
git clone https://github.com/diaplus97/Shorts.git shorts-factory
cd shorts-factory
git checkout claude/can-you-build-this-e8v5k5

# A fresh clone has no .env. Copy the whole one across -- it is a single file
# and the keys in it are the same ones.
cp /c/Users/SAMSUNG/Shorts/Shorts/.env .env

# Writes config/settings.local.yaml: picks the Korean font for this OS and
# points projects at another drive. Editing that YAML by hand is how a
# backslash in a Windows path becomes a failed run twenty minutes later.
./run.sh --setup --project-root D:/shorts-projects

# Use this instead when a key is missing from an .env you already have. It
# searches the machine and appends the matching line without opening either
# file, so the value never reaches a terminal or a shell history.
# bash scripts/import_key.sh FAL

./run.sh --doctor                   # creates the venv, installs, checks ffmpeg and keys
./run.sh --probe                    # one fal call
```

### PowerShell

`run.sh` will not run here; these are the steps it performs.

```powershell
cd C:\Users\SAMSUNG
git clone https://github.com/diaplus97/Shorts.git shorts-factory
cd shorts-factory
git checkout claude/can-you-build-this-e8v5k5

py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

# Copy the .env across yourself: the import script is bash.
copy C:\Users\SAMSUNG\Shorts\Shorts\.env .env

.venv\Scripts\python scripts\doctor.py
.venv\Scripts\python scripts\probe_fal.py
.venv\Scripts\python -m shorts_factory create "ATM은 어떻게 지폐를 셀까?"
```

### Keeping the video off the system drive

The repository is small; what grows is `projects/`, at several GB per Short.
Point it at another drive in `config/settings.local.yaml` -- forward slashes
are fine on Windows:

```yaml
project_root: D:/shorts-projects
```

Cloning the repository itself onto an SD card is the worse half of that trade:
installing the virtualenv writes thousands of small files, which is the access
pattern SD cards are slowest at.

### What has to be installed first

- **Python 3.12+** — `winget install Python.Python.3.12`
- **ffmpeg with libass**, on `PATH` — `winget install Gyan.FFmpeg`, then reopen
  the terminal. `ffmpeg -filters | findstr subtitles` must print a line, or
  burned-in subtitles cannot render.
- **A Korean font.** Windows has Malgun Gothic; set
  `subtitles.font_name: Malgun Gothic` in `config/settings.local.yaml`, because
  the default is the Linux `Noto Sans CJK KR`.
- `config/settings.local.yaml` — copy `config/settings.local.yaml.example` and
  edit. Without it every provider is a mock and the run produces
  `mock_preview.mp4` rather than a Short.

`.env` and `config/settings.local.yaml` are both gitignored, so neither comes
with the clone and neither will ever be committed.


## Requirements

- Python 3.12+
- ffmpeg and ffprobe on `PATH`, built with libass for subtitle burn-in
- A Korean-capable font installed (default: `Noto Sans CJK KR`)
