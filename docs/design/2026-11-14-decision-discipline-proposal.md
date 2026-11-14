# Proposal: discipline on design decisions (schema 1.2)

Date: 2026-11-14. From: UI/UX lead. To: the owner of the design-record schema.
Status: proposal. Nothing in the schema changes until the owner accepts it.

## Problem

PRD D7 needs a decision per candidate with its reason and the reviewer's discipline (basic design,
structure, machinery, outfitting, accommodation). The schema 1.1 `decision` has `id`,
`candidate_id`, `action`, `reason`, `designer_id`, `recorded_at` and `status`, with
`additionalProperties: false`. It has no place for the discipline.

## Interim (phase 2 of the workbench UI)

The app keeps phase-2 decisions in a sidecar file beside the records:
`<runs folder>/designs/decisions/<project design_id>.json`, schema tag
`marinaframe.design_decisions.v0`. Each entry has the schema 1.1 decision fields plus `discipline`.
The file is append-only; the latest entry per candidate and discipline is the current one. The
records themselves do not change.

## Proposed change

Add an optional field to `$defs/decision` in a schema 1.2:

```json
"discipline": { "enum": ["basic_design", "structure", "machinery", "outfitting", "accommodation"] }
```

Optional, so every 1.1 record stays valid. When 1.2 exists, the app moves the sidecar decisions
into the project's parent record (`designer_decisions`, with `candidate_id` set to the candidate's
`design_id`) and stops writing the sidecar.

## Checks for the owner

- The Rust and Python validators accept a 1.1 record unchanged and a 1.2 record with `discipline`.
- The migration keeps `id`, `recorded_at` and order, so no decision is lost or duplicated.
