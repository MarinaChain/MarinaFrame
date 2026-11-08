# W17: investigator progress

## Scope

W17 changes the live investigator, not contour tolerances, geometry validation, or the factory gate. All model assignments remain open `model_choice` guesses. `engineering_approved` remains false. Drafts cannot be promoted to human-review readiness while guesses remain open.

The sealed v2 comparison is spent. This work does not rerun it or tune on its drawings/results. The supplied failure analysis is historical context. Development measurements use only `benchmarks/factory/manifests/cases.jsonl` rows with `split=development`.

## Causes

1. Decision events store reasoning at `payload.decision.reason`; the observation read `payload.reason` and returned null.
2. A reading tool returns source pixels, not OCR or certified identity. Stateless requests had no field to retain the model's own reading.
3. Identical actions were executed repeatedly until the controller stopped, without a corrective observation first.
4. The isolated inspection worker discarded typed failure reasons. A contour-evidence resource limit left no catalog entry, so all bounded tracing tools refused with `section_not_inspected`.
5. Enumerated vertical station/grid strokes looked like ordinary hull candidates.
6. Investigation requests fixed thinking off and temperature zero, without a way to measure alternatives.

## Changes and safety

### History and working memory

The observation reads the nested recorded reason. Decisions accept optional `notes`, limited to 600 Unicode characters and 2,400 bytes. The latest eight executed live-model notes appear as `your_notes_newest_first`. Each item says `verified=false`, `source=model_claim`; the observation explicitly says these are not measurements or certified identities. Absent notes are omitted on serialization so older ledger hashes remain valid.

The prompt asks the model to record label positions and tag-to-station claims, then act on those claims rather than repeatedly requesting the same crop. It still prohibits model-written line coordinates. Rough view-space points/corridors remain inputs to code that measures real ink.

### Repeat feedback

Before executing a repeated live investigation action, the controller compares its tool/arguments and meaningful domain state against earlier decisions. New crops do not count as geometry progress. Generation, revision, catalog evidence, guesses, sheet setup and current build do. A repeated action returns `repeated_action_refused`, cites the earlier decision/result event and view ID, and offers next operations such as assignment or draft build. It does not call the worker. Refusals are counted under the same repeat limit; the hard stop remains.

### Resource-limit recovery

The worker emits a fixed `resource_limit` code/message only for a typed drawing/resource exception with that exact code. Other failures remain generic. No arbitrary exception message, source path, request or secret is copied to the model observation.

After a known resource-limit failure, the parent records source-bound empty catalog entries for the affected requested sections. These are **failed-inspection placeholders**, not successful inspections or invented candidates. `inspected=false` and `inspection_failure=resource_limit` remain visible, including on cached inspection calls. Catalog availability means the section can be accounted for in a draft, not that its geometry or identity was established.

This is the smallest recovery design because existing tracing/enumeration tools already require catalog membership, measure bounded real ink, and refuse unsupported lines. No extraction budget is raised. A placeholder has no selectable contour. Tracing can add only engine-verified candidates. Enumeration alone does not assign them. Assignment still needs task-bound label evidence, preserves one-ink/one-station checks, and records an open guess. Unassigned traced candidates cannot become automatic best-score guesses. Empty sections remain disclosed gaps/end guesses under the existing draft rules. Arbitrary worker failures, cancellation and timeouts do not unlock tools.

### Grid evidence

Enumeration adds `kind=straight_grid_line` for traces that span at least 95% of the declared calibrated section height and vary by at most two source pixels in x. The two-pixel bound allows raster thickness, not curve fitting. Other traces are `candidate_stroke`. This is a visual classification, not identity certification or a selection rule. All evidence and tags remain available. Row-indexed sustained section traces do not enumerate horizontal grid lines as hull strokes.

### Provider settings

`run` accepts:

- `--investigation-thinking disabled|enabled` (default `disabled`).
- `--investigation-temperature 0..2` (default `0`; finite values only).

These are recorded in the existing operational configuration. Default fields are omitted to preserve old serialized configurations. They affect only investigation requests; other provider purposes retain their settings. Defaults remain unchanged pending development evidence.

## Development measurement

The sample was fixed from metadata before inference: the first three sorted development hull IDs in each layout, all L0–L3 levels. This gives 24 cases, three per layout/noise cell. It is a balanced diagnostic sample, not a population-weighted estimate.

Inputs were regenerated with the existing factory generator. All drawing, spec, params and development-truth hashes match the frozen manifests. Raw data and logs are under the main checkout's `work/w17/`, not this worktree. Each arm uses an immutable executable and Python source snapshot. Runs use `--policy live --on-ambiguity draft --model-review true`, at most two task jobs, and the existing native worker admission lock. No per-controller temporary directory splits the lock namespace.

The scorer is the existing factory STEP scorer. Correctness uses the unchanged gate: section RMS at most 2% of maximum truth half-breadth and absolute in-range volume error at most 5%. The denominator remains 24 even for blocked or failed attempts. A silent wrong build is an `awaiting_human_review` export that fails this gate; wrong non-review-ready drafts are labelled separately. Provider request/list-cost accounting includes investigation, review and failed attempts; missing list cost is not assumed zero.

### Results (in progress)

Baseline `a5fd140`: 22/24 `no_progress` (91.7%), two `draft_not_verified`; one actual STEP export, one gate-correct, zero silent wrong builds, zero labelled wrong exports. There were 221 provider receipts, list cost USD 0.23715584, no missing list costs. One draft status had no valid export and is not counted as built.

The PM stopped the after-change campaign deliberately after four DTMB cases. Do not restart it. L0 and L1 reached draft builds but produced no STEP: L0 failed on unreliable/unresolved s01; L1 assigned all nine stations but failed on an interior centreline pinch in s04. L0 rebuilt the blocked selection repeatedly. Both ended `no_progress` through repeat refusals. L2 and L3 were interrupted during provider requests when the campaign was stopped. Thinking-on was not run; defaults remain unchanged.

| Stopped after case | Status | STEP drafts | Gate-correct | Requests | Known list cost USD |
|---|---|---:|---:|---:|---:|
| dtmb5415-L0 | no_progress | 0 | 0 | 40 | 0.05406369 |
| dtmb5415-L1 | no_progress | 0 | 0 | 29 | 0.04641752 |
| dtmb5415-L2 | interrupted | 0 | 0 | 8 | 0.00900225 |
| dtmb5415-L3 | interrupted | 0 | 0 | 6 | 0.00597825 |

Known list cost totals USD 0.11546171 across 83 receipts; the two interrupted requests have unknown cost, not zero cost. No silent wrong builds occurred. These four cases show that investigation now reaches assignments/builds, but draft geometry gates discard the work. The founder redirected work to draft CAD first and four-case rounds, not another large campaign. Compact outcomes go in `outputs/w17/`; no drawings, truth arrays or keys are included.

## Verification and resume

- History test failed before fix with actual null reason, then passed.
- Optional notes contract and retention tests pass.
- Repeat-refusal count/earlier-view/state-change unit test passes.
- Python investigation tests pass, including resource-limit recovery, generic-failure refusal, no automatic selection, and straight/curved/short classification.
- `make test-quick`: passed (712 Python tests, 18 CAD tests deselected; Rust workspace/lint passed; secret pattern scan had zero findings).
- `make test-full`: passed, including Rust real-CAD guards, app real-task integration, 18 Python CAD tests, and smoke (`awaiting_human_review`, verify valid). Log: main `work/w17/test-full.log`.

Reproduction driver: `scripts/w17_dev_campaign.py prepare|run|score --arm baseline|after|thinking`. It refuses to overwrite an attempt directory. See `docs/plans/2026-11-08-w17-llm-progress.md` for boundaries. W17 is the checkpoint before W17b draft-only geometric repairs. Do not resume the stopped after/thinking campaign. W17b uses DTMB L0–L3 rounds first; only a round with at least three STEP drafts permits one 24-case development run. Commit only on `w17-llm-progress`. Do not push or merge.
