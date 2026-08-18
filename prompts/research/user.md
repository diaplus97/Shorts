TOPIC: {{topic}}
CONTENT_TYPE: {{content_type}}
CONTENT_TYPE_LABEL: {{content_type_label}}
TARGET_CLAIMS: {{target_claims}}

Content-type framing:
{{content_type_description}}

Below are the search results already retrieved for this topic. They are the only
sources you may cite. Each has a stable `id`.

SOURCES_JSON:
```json
{{sources_json}}
```

Produce a `ResearchResult` object with these fields:

- `topic`: echo the topic verbatim.
- `question`: `{ original_topic, resolved_question, scope, excluded }` — the
  normalisation described in your instructions.
- `summary`: 3-5 Korean sentences explaining how this specific mechanism works,
  naming real parts.
- `claims`: about {{target_claims}} atomic claims, ids `C01`, `C02`, ...
  Each needs `statement`, `confidence`, `source_ids`, `visualizable`.
- `sources`: echo back every source you cited, unchanged.
- `unresolved_questions`: what you could not confirm from these sources.
- `unsafe_or_uncertain_claims`: statements that sounded plausible but that the
  supplied sources do not actually support.

Return the JSON object only.
