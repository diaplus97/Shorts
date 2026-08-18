# 0002 — project.json is the canonical state

## Status

Accepted.

## Context

The pipeline spends real money on video generation. A crash must never cost
that money twice, and no database belongs in an MVP that runs on one machine.

## Decision

Each project is one directory. `project.json` holds stage status, paths, the
provider set and cost totals. Stage outputs are sibling files
(`research.json`, `script.json`, `scenes.json`, `assets.json`, `manifest.json`).
Costs are appended to `logs/costs.jsonl` as they are incurred.

Every write goes through `atomic_write_*`: a temporary file in the destination
directory, fsynced, then `os.replace`.

## Consequences

- Resume is "read the files and skip what is done".
- The cost ledger is rebuilt from the JSONL, so budget limits hold across
  restarts rather than resetting with the process.
- Inspecting or archiving a project is `ls` and `cat`.
- Concurrent runs against one project directory are not supported. That is
  acceptable for a single-operator CLI.
