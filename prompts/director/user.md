TOPIC: {{topic}}
CONTENT_TYPE: {{content_type}}
DEFAULT_REALITY_TYPE: {{default_reality_type}}
MIN_SCENES: {{min_scenes}}
MAX_SCENES: {{max_scenes}}
TARGET_DURATION_SEC: {{target_duration_sec}}
MIN_SCENE_DURATION_SEC: {{min_scene_duration_sec}}
MAX_SCENE_DURATION_SEC: {{max_scene_duration_sec}}
MAX_HIGH_PRIORITY_SCENES: {{max_high_priority_scenes}}
CHARS_PER_SEC: {{chars_per_sec}}

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

The finished narration you must cover, in order:

SCRIPT_JSON:
```json
{{script_json}}
```

The verified claims behind it:

CLAIMS_JSON:
```json
{{claims_json}}
```

Produce a `ScenePlan` object:

- `scenes`: ids `S01`, `S02`, ... with ascending `order` starting at 1, and the
  fields `narration`, `duration_sec`, `purpose`, `visual_subject`,
  `environment`, `action`, `camera`, `framing`, `lighting`, `reality_type`,
  `priority`, `asset_type`, `continuity`, `claim_ids`, `transition_in`,
  `transition_out`, `negative_constraints`.
- `continuity`: every recurring object or location, each with a
  `continuity_id` and one `fixed_description`.
- `visual_notes`: anything the compositor should know.

Return the JSON object only.
