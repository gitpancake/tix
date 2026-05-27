---
linear:                       # Linear ID once synced; empty = draft
title: <≤80 chars, action-oriented, no fluff>
status: draft                 # draft | open | active | done — cache, reconciled not hand-edited
epic:                         # parent epic folder slug, or empty
area: integrations            # integrations | platform | ops | tooling | spikes
labels: []
created: <ISO-8601 UTC instant, e.g. 2026-05-27T18:13:00Z — date-only falls back to file birthtime>
---

## Context
<2–4 sentences — why this exists. Quote the slack / email / customer / trace source.>

## Acceptance criteria
- <bulleted, each independently verifiable>

## Surface area
- **Mirror**: `<feature/file>` — one-line why it's the structural twin.
- **Files to start in** (≤8): `path — reason`.
- **Gotchas**: quoted project CLAUDE.md rules that apply.

## Out of scope
- <explicit — better to over-list>

## Open questions
- **Ambiguous**: <question + who to ask: teammate / customer / #eng-chat>
- **Risky**: <blast radius + rollback path>

## Prerequisites
<env vars to set, accounts to provision, infra to stand up. None → "none.">

## Local notes
<!-- lane / agent scratch — preserved across any later /sync-from-linear -->
