TOPIC: {{topic}}
CONTENT_TYPE: {{content_type}}
TARGET_DURATION_SEC: {{target_duration_sec}}
MIN_DURATION_SEC: {{min_duration_sec}}
MAX_DURATION_SEC: {{max_duration_sec}}
CHARS_PER_SEC: {{chars_per_sec}}
TARGET_CHARS: {{target_chars}}
MIN_CHARS: {{min_chars}}
MAX_CHARS: {{max_chars}}

Narration length is measured in Korean characters excluding whitespace. Stay
between MIN_CHARS and MAX_CHARS, aiming for TARGET_CHARS.

Research summary:
{{research_summary}}

These are the only verified claims available. Cite them by id.

CLAIMS_JSON:
```json
{{claims_json}}
```

Produce a `ScriptResult` object:

- `title`: a Korean title under 40 characters.
- `hook`: the first sentence, repeated verbatim as the first beat's text.
- `narration`: the full narration, beats joined by single spaces.
- `beats`: ids `B01`, `B02`, ..., each with `purpose`
  (one of `hook`, `reveal`, `process`, `surprise`, `closing`), `text`
  and `claim_ids`.
- `target_duration_sec`: your estimate, MIN_DURATION_SEC..MAX_DURATION_SEC.
- `referenced_claim_ids`: every claim id used anywhere in the script.
- `estimated_word_count`: whitespace-separated token count of `narration`.

Return the JSON object only.
