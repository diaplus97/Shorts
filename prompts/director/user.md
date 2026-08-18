TOPIC: {{topic}}
RESOLVED_QUESTION: {{resolved_question}}
SCOPE: {{scope}}
CONTENT_TYPE: {{content_type}}
DEFAULT_REALITY_TYPE: {{default_reality_type}}
MIN_SCENES: {{min_scenes}}
MAX_SCENES: {{max_scenes}}
TARGET_DURATION_SEC: {{target_duration_sec}}
MIN_SCENE_DURATION_SEC: {{min_scene_duration_sec}}
MAX_SCENE_DURATION_SEC: {{max_scene_duration_sec}}
MAX_HIGH_PRIORITY_SCENES: {{max_high_priority_scenes}}
MAX_CAPTION_CHARS: {{max_caption_chars}}

Reveal pattern for this content type:

REVEAL_PATTERN_JSON:
```json
{{reveal_pattern_json}}
```

Preferred camera moves:

PREFERRED_CAMERA_JSON:
```json
{{preferred_camera_json}}
```

Preferred visual devices:

PREFERRED_VISUALS_JSON:
```json
{{preferred_visuals_json}}
```

Transitions that keep the world continuous:

TRANSITIONS_JSON:
```json
{{transitions_json}}
```

The finished narration you must cover, in order:

SCRIPT_JSON:
```json
{{script_json}}
```

The speech units to cover. Each scene takes whole units, in order, and every
unit must be used exactly once:

SPEECH_UNITS_JSON:
```json
{{speech_units_json}}
```

The verified claims behind it:

CLAIMS_JSON:
```json
{{claims_json}}
```

Produce a `ScenePlan` object:

- `world`: `{ machine_id, visual_style, environment, notes }` — the one machine
  and location every scene shares.
- `continuity`: the registry of recurring objects and locations, each with a
  `continuity_id` and one `fixed_description`.
- `scenes`: ids `S01`, `S02`, ... with ascending `order` starting at 1, and the
  fields `narration`, `caption`, `subtitle_position`, `duration_sec`, `purpose`,
  `question_answered`, `key_object`, `mechanism`, `visible_change`,
  `visual_subject`, `environment`, `action`, `camera_path`, `framing`,
  `lighting`, `reality_type`, `priority`, `asset_type`, `speech_unit_ids`,
  `continuity_ids`, `claim_ids`, `transition_in`, `transition_out`,
  `negative_constraints`.
- `visual_notes`: anything the compositor should know.

Return the JSON object only.
