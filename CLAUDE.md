# CLAUDE.md

Read `AGENTS.md` before making implementation changes.

`AGENTS.md` is the canonical engineering policy for this repository.

Read the implementation specification before architecture-level changes:

`docs/IMPLEMENTATION_SPEC.md`

Important constraints:

- MVP is CLI-first.
- Do not add a web application.
- Do not add a multi-agent runtime.
- Do not add infrastructure not required by current acceptance criteria.
- Prefer small, testable modules.
- Run tests and lint after implementation changes.

These notes are context, not enforcement. The rules that must not be broken are
enforced by tests, schema validation and CI:

- paid API calls in tests are blocked by `assert_live_calls_allowed`,
- unsourced claims are blocked by the fact lock,
- cost overruns are blocked by the budget guard,
- output format is checked with ffprobe,
- silent audio and mock providers are blocked by the production readiness gate,
- scene/speech misalignment is blocked by the speech contract.
