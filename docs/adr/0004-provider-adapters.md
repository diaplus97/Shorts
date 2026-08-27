# 0004 — Providers behind protocols, one implementation each

## Status

Accepted.

## Context

Video, image, TTS and search vendors change quickly: pricing, model names,
clip length limits and job semantics all move. Meanwhile an abstraction built
before a second implementation exists is usually the wrong abstraction.

## Decision

`providers/base.py` defines the protocols. `providers/registry.py` builds the
set named in `config/settings.yaml`. Exactly one real implementation per kind is
wired up; a mock always exists alongside it.

Scenes never carry a provider prompt string. A `VideoPromptAdapter` turns a
`Scene` into vendor text, so changing vendors does not touch the director.

Video generation is assumed to be asynchronous — submit, poll, download — even
for the mock, so the real integration does not change the calling code.

## Consequences

- The whole pipeline runs offline against mocks.
- Registry errors point at the phase in the spec that adds the missing provider.
- Adding a vendor means one module and one registry branch.
