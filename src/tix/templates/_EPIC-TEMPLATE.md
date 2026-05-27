---
linear:                       # Linear epic ID once synced; empty = draft
title: <epic name, ≤80 chars>
status: open
area: integrations            # integrations | platform | ops | tooling | spikes
created: <ISO-8601 UTC instant, e.g. 2026-05-27T18:13:00Z — date-only falls back to file birthtime>
---

## Context
<why this epic exists — the problem, the trigger, the source.>

## Goal
<one sentence — the end state when the epic is done.>

## Acceptance criteria
<epic-level "done when" — the integration test for the whole thing, not per-story.>

## Constraints
<non-negotiables; load-bearing facts every story inherits. None → "none.">

<!--
  epic-stories: the authoritative ordered story list + dependency DAG.
  A human confirms this block before any lane spawns. epic-parse.sh projects it
  into scripts/ralph/prd.json at lane-spawn. Ralph executes it — it never decomposes.
    id      — matches the child filename, NN-<slug> (NN = execution order)
    needs   — story ids this one depends on; [] = ready immediately
    context — the NN-<child>.md file carrying this story's deep detail
-->
<!-- epic-stories:start -->
stories:
  - id: 01-<child-slug>
    title: <story title>
    needs: []
    context: 01-<child-slug>.md
  - id: 02-<child-slug>
    title: <story title>
    needs: [01-<child-slug>]
    context: 02-<child-slug>.md
<!-- epic-stories:end -->

## Local notes
<!-- lane / agent scratch — preserved across any later /sync-from-linear -->
