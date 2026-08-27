# 0001 — A deterministic pipeline, not an agent swarm

## Status

Accepted.

## Context

The obvious way to build this is one agent per job: research agent, fact agent,
hook agent, script agent, scene agent, prompt agent, video agent, QA agent.
Each hand-off then carries the whole conversation, roles overlap, and a bad
result is hard to attribute to a step.

## Decision

The runtime is an ordered list of stages. Each stage is an ordinary async
function that takes a `RunContext` and persists its own output. An LLM is called
at exactly three points — research, writing, directing — plus an optional
fact-check pass. Everything else is deterministic code.

## Consequences

- A failure names the stage that produced it.
- Re-running a stage is cheap and its blast radius is explicit: downstream
  stages are invalidated, upstream results are kept.
- Prompt changes affect one stage.
- Development agents (Codex, Claude Code) remain useful for *building* this;
  they are simply not part of the runtime.
