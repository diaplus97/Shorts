TOPIC: {{topic}}

NARRATION:
{{narration}}

CLAIMS_JSON:
```json
{{claims_json}}
```

Produce a `FactCheckReport` object:

- `unsupported_sentences`: list of objects with `sentence` and `reason`.
- `overreaching_sentences`: list of objects with `sentence` and `reason` for
  sentences that are directionally right but claim more than the evidence.
- `verdict`: `pass` when both lists are empty, otherwise `fail`.
- `notes`: optional reviewer notes.

Return the JSON object only.
