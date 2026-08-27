TOPIC: {{topic}}
RESOLVED_QUESTION: {{resolved_question}}
SCOPE: {{scope}}
EXCLUDED: {{excluded}}
CONTENT_TYPE: {{content_type}}
TARGET_DURATION_SEC: {{target_duration_sec}}
MIN_DURATION_SEC: {{min_duration_sec}}
MAX_DURATION_SEC: {{max_duration_sec}}
CHARS_PER_SEC: {{chars_per_sec}}
TARGET_CHARS: {{target_chars}}
MIN_CHARS: {{min_chars}}
MAX_CHARS: {{max_chars}}
HOOK_MAX_SECONDS: {{hook_max_seconds}}
HOOK_MAX_CHARS: {{hook_max_chars}}
MAX_GENERIC_NOUNS: {{max_generic_nouns}}
MAX_UNIT_CHARS: {{max_unit_chars}}
NARRATOR_PERSONA: {{persona}}
NARRATOR_FORMALITY: {{formality}}

Keep each spoken sentence at or under MAX_UNIT_CHARS characters. A longer one
will be split automatically, and an automatic split reads worse than one you
wrote.

Write about the RESOLVED_QUESTION, not the looser TOPIC. Stay inside SCOPE and
say nothing about anything in EXCLUDED.

Narration length is measured in Korean characters excluding whitespace. Stay
between MIN_CHARS and MAX_CHARS, aiming for TARGET_CHARS.

These words may appear at most MAX_GENERIC_NOUNS times in total across the whole
narration:

GENERIC_NOUNS_JSON:
```json
{{generic_nouns_json}}
```

Research summary:
{{research_summary}}

These are the only verified claims available. Cite them by id. `visualizable`
tells you which ones can carry a shot.

CLAIMS_JSON:
```json
{{claims_json}}
```

Produce a `ScriptResult` object:

- `title`: a Korean title under 40 characters.
- `hook`: the first sentence, repeated verbatim as the first beat's text. It
  must pose a question and fit inside HOOK_MAX_SECONDS.
- `narration`: the full narration, beats joined by single spaces.
- `beats`: ids `B01`, `B02`, ..., each with `purpose`, `text`, `claim_ids`,
  `visualizable`, `visual_payoff`, and optionally `emphasis`: one word from
  `text` to highlight on screen. Use it on the two or three beats that carry the
  point, not on every one.
- `target_duration_sec`: your estimate, MIN_DURATION_SEC..MAX_DURATION_SEC.
- `resolved_question`: echo RESOLVED_QUESTION verbatim.
- `referenced_claim_ids`: every claim id used anywhere in the script.
- `estimated_word_count`: whitespace-separated token count of `narration`.

Return the JSON object only.
