# W18 Native Conversation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give the investigator bounded conversational memory while keeping the controller authoritative and drafts useful.

**Architecture:** Project completed investigation receipt decisions and subsequent host observations from the existing event ledger. Keep paired recent messages and fold older steps into an author-labelled controller record plus the model's latest unverified notes. Reuse existing provider worker, images, receipts and limits; no framework dependency.

**Tech Stack:** Rust/serde_json, existing event store and provider adapter, Python tools unchanged.

---

Section 0 of `2026-11-08-w18-agent-loop-design.md` governs. Heavy covered-event hashes, unresolved-ID machinery and exact payload replay proof are deferred. Default stays stateless, thinking disabled. The W17b frozen dev batch is independent of edits here.

1. Add `transcript.rs` under controller with compact-result whitelist, receipt-derived steps, progress line, pair-preserving history and deterministic byte/3 + 800/image token estimate. Unit tests: fields dropped, refusal retained, latest observation present, budget stop, restart projection.
2. Add backward-compatible operational settings for conversation/context budget (32k default, 8k–120k bounds), omitted defaults to preserve old ledger hashes. CLI `--context stateless|conversation`, `--max-context-tokens`.
3. Conversation-only branch in live request builder; persist author-labelled `context_compacted` event, pass context metrics into provider intent. Do not duplicate W17 history/notes in latest observation.
4. Provider validator accepts alternating historical string messages and images only in final user content. Preserve image inventory, hashes and PNG checks.
5. Add controller-only `recall_view` with bounded known ID, recall-first image ordering, repeat refusal. Preserve model-choice and engineering approval rules.
6. Keep notes-based unverified handoff initially; dedicated model compaction request remains an explicit follow-up unless small rounds justify its added cost. Document this design gap, not a false claim of full section 4a completion.
7. `make test-quick`, small DTMB conversation round after W17b dev batch ends (two jobs total), inspect traces and score. Do not launch another broad run without three drafts. `make test-full` before commit/report.

Resume: W17 `46363f6`, W17b `68afb96` committed; W17b dev24 running frozen. W18 conversation projection/config/recall implemented, quick tests running. Next: tests for provider history/recall and privacy, review, freeze W18 runtime then four-case round. No push or merge.
