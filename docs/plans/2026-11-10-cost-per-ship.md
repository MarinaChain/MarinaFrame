# Cost per Ship Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Measure stored hull and tank run resources without new inference or image access.

**Architecture:** A standard-library script normalizes stored controller and holdout receipts. Source paths and missing fields remain explicit; summaries are cross-checks, not extra calls. Inclusive wall time is separate from summed model and worker time.

**Tech Stack:** Python 3.12, JSON/JSONL, pytest, Markdown.

---

## Review

- Architecture: PASS. One offline script; no product changes.
- Quality: WARN. Summary duplication, cumulative CLI usage, and collapsed cache counters need explicit rules.
- Tests: PASS. Use synthetic receipts to check distinct calls, cached tokens, missing usage and inclusive timings.
- Performance: PASS. Read only selected text records, not images or full work trees.

## Checkpoint 1: stored record accounting

Create `scripts/cost_per_ship.py` and `tests/test_cost_per_ship.py`. Read controller/transport and holdout harness source before implementing adapters. Read main checkout `work/round-3view-*-sonnet-*`, `work/autocal-live-*`, and the three requested holdout run trees only. Locate tank records; if removed, state this and use the existing tank report only as secondary evidence. Run `PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_cost_per_ship.py -q` and the script offline. Commit script, tests and this plan.

## Checkpoint 2: dated prices

Add a dated USD/MTok table for the four requested models. Use bundled Claude references, not memory; distinguish cache writes and reads. Do not infer a Claude price from the CLI's list_cost. Missing prices stay null. Verify arithmetic offline; commit.

## Checkpoint 3: report

Create `docs/COST_PER_SHIP.md` and a compact text-only accounting ledger in `outputs/`. Include per-case, per-arm, per-model and per-phase counts, timings and costs; the hull-plus-tanks planning range; source and scope limits; three drivers; measured cheaper alternatives and accuracy limits. Do not label a stitched estimate as a measured complete ship. Run tests, regenerate ledger, review consistency, commit.

## Resume point

Start with checkpoint 1. Inspect `git log -3` and `git status --short` to find completed checkpoints. Stay on `feature/cost-per-ship`. Never push, merge, switch branches, read images, or launch inference. Main checkout records are read-only. Commit after each checkpoint. Final reply is under 150 words.
