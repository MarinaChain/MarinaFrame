# MarinaFrame 0.2: implementation and validation results

**Report date: 7 November 2026, Asia/Singapore.** Tests ran on 6 November UTC.
This continuation implements and tests a substantially stronger local research
system. It does not establish arbitrary ship-plan understanding, a remote
production service, a completed authentic archival reconstruction, or qualified
engineering approval.

## Revision and evidence scope

- Repository: <https://github.com/MarinaChain/MarinaFrame>.
- Exact starting revision: `7b1a736a0b6c800f8d6dcfe6d59729731b8d7f11`.
- Local branch: `hardening/2026-11-07-evidence-runtime-geometry`.
- The final commit and patch hashes are recorded in the separate release receipt.
  No remote branch, pull request, deployment, repository visibility change or
  license change was made.
- The observed remote CI success belongs to the **base revision**, run
  [42245209146](https://github.com/MarinaChain/MarinaFrame/actions/runs/42245209146).
  The new local branch has **not** run on GitHub Actions.
- The optional `/workspace/shared/marina-review` review tree was absent. The
  previous foundation workspace and its exact 47-case frozen dataset were
  available locally. They were distinguished from the public source-only import.

Source paths below are relative to the checkout. Unless prefixed explicitly,
evidence paths are relative to `artifacts/hardening/`. Large generated artifacts
are excluded from Git. The separate validation archive contains an indexed selection
of reports, commands, fixtures and success/failure evidence; its inventory states
which historical inputs and large exports are omitted. Hashes establish byte
consistency, not independently certified chronology or an external signature.

## What was completed

The offline core still measures calibrated half-section drawings and builds a
real CadQuery/OpenCascade boundary-representation hull envelope. It now uses
typed and bounded input validation, competing-contour evidence, error-bounded
section correspondence, transactional publication, complete immutable records,
separate review events, durable local jobs and resource-limited subprocesses.
The browser workbench authenticates a local session, exposes source and candidate
overlays, reports CAD approximation, and gates downloads on complete verification.

The caller still supplies regions, station coordinates, scale, datum, vertical
extent and symmetry. Between-station interpolation and terminal/top/lower
closures remain declared modeling assumptions. Inputs and JSON geometry use
metres; CAD, STEP and STL use millimetres. STL contains no unit declaration.
Every successful model remains `review_required`, with
`engineering_approved=false`.

**The central regression is explicit: the unchanged historical replay produced
0/42 numerical completions under the stronger contour policy.** Two separately
identified known cases succeeded with newly recorded pixel-selection assistance.
Those two results do not replace the 0/42 unassisted result. The separate generated
development drawing still reconstructs all 21 sections without selection corridors.

## Finding-by-finding disposition

| Finding | Reproduction and disposition | Regression coverage and retained evidence |
| --- | --- | --- |
| **A. Late failure leaves successful/exportable geometry** | Reproduced on the exact base with a generated fixture and a required-evidence write failure. Fixed for the exercised application paths: private staging, exclusive reservation, required evidence before sealing, no-replace atomic publication, durability checks and export-free recovery. Later inconsistent publication states, including 15 final replay records, remain unresolved; see below. | `tests/test_evidence_hardening.py`: `test_required_write_failure_never_publishes_success_or_geometry`, `test_copy_export_hash_and_publication_failures_withdraw_geometry`, `test_parent_sync_failure_after_rename_never_admits_geometry`, reservation/recovery tests. Evidence: `artifacts/hardening/evidence/`, `installed-wheel-final/`, `exclusive-publication-probe/`. |
| **B. Preview bypasses resource limits** | Reproduced: scale 10,000 reached the PDF renderer; interception prevented allocation. Fixed primary and reference preflight before render/decode, aggregate work bounds and bounded native workers. | `tests/test_resources.py`: PDF DPI/page/pixel, raster header bomb, aggregate reference and table amplification tests. `tests/test_runtime.py`: process limits. Evidence: `runtime/baseline_reproduction.json`, `runtime/runtime_validation.json`. |
| **C. Untrusted Host/Origin and missing authentication** | Reproduced with controlled loopback requests: hostile matching headers received inventory 200/upload 202 at the base. Fixed for the supported local profile with exact trusted authorities, one-use bootstrap, authenticated API reads, session CSRF and refusal of remote binding. No browser DNS-rebinding exploit is claimed. | `tests/test_server.py`, independent `geometry/runtime-probe/report.json`, browser assertions in `browser/report.json`. Local session possession is not verified reviewer identity. |
| **D. Incomplete verification** | Reproduced metric/station/replay tampering that still verified at the base. Fixed local integrity and internal consistency with result schema 2, complete noncircular manifests and derived checks. This is not authenticity against wholesale replacement of the manifest and all files. | `tests/test_evidence_hardening.py`: `test_each_authoritative_artifact_is_hash_bound`, `test_result_semantics_reject_inconsistency_even_after_rehash`, stripped/empty manifest, traversal/symlink and immutable review tests. Evidence: `evidence/ENGINEERING_NOTES.md`. |
| **E. In-memory, unbounded and unkillable work** | Original architectural limitations confirmed. Implemented SQLite jobs, admission before upload, source/spec hashes, idempotency, bounded pending capacity/storage, deadlines, streaming, subprocess limits, cancellation, expiry, restart recovery, readiness and quiescent backup/restore. Controlled faults passed; production load/power-loss behavior is not established. | `tests/test_runtime.py`, `tests/test_server.py`; independent HTTP/process/publication/queue probes total **37/37**. Evidence: `geometry/RUNTIME_INDEPENDENT_REVIEW.md`, `runtime/`, `geometry/runtime-*-probe/`. |
| **F. Malformed input escapes the evidence contract** | Reproduced `input_mode=[]` raising outside structured handling at the base. Fixed the reported case and tested malformed classes with bounded JSON and complete typed validation before native work. Persistent storage failure still cannot promise a durable error file. | `tests/test_evidence_hardening.py`: wrong top-level/nested types, duplicate/nonfinite/huge/deep JSON, booleans, invalid references, FIFO inputs, and no-CAD-import early rejection. |
| **G. Faint competing contours disappear** | Reproduced five unequal-contrast cases choosing the wrong inner line with quality 1.0. All six original contrast cases now abstain and retain candidate evidence. Explicit caller-supplied pixel selection is supported. General semantic understanding remains incomplete, with a substantial old-benchmark completion regression. | `tests/test_contrast.py`, `tests/test_semantic_adversaries.py`, `tests/test_integration_adversaries.py`, `tests/test_pixel_corridor_proposals.py`; `geometry/frozen-baseline/`, `fixed-reproducer/`, `assisted-regression/`. |
| **H. Fixed resampling erases local shape** | Reproduced a 6 m beam narrow peak becoming 2 m while volume error stayed small. Replaced fixed 33-level resampling with adaptive source-knot correspondence and an explicit 1 mm default half-breadth approximation bound. Actual STEP boundary cuts verify the analytic fixtures. Unsupported topology and excessive complexity block. | `tests/test_geometry_adversaries.py`, `benchmarks/audit_geometry_hardening.py`; `geometry/analytic-step-audit/report.json`. Absolute STL tessellation deflection is separately recorded. |

The reports retain original failures and later successful repetitions. A passing
integrity check on a blocked record means its failure evidence is intact;
`exports_allowed` remains false. It does not mean reconstruction succeeded.

## Actual executed checks

The exercised environment is **Linux x86_64, Python 3.12.14, CadQuery 2.7.0,
OCP 7.8.1.1.post1**. Other Python minor versions and operating systems are not
validated. Package support was narrowed to Python 3.12 and the documented Linux
worker/publication profile.

| Check run here | Result | Evidence |
| --- | --- | --- |
| Unchanged base pytest | **101 passed in 27.05 s** | `baseline/pytest.txt`, `baseline/pytest.xml` |
| Base development generation, CLI, reconstruction and verification | All passed; reconstruction **9.29 s**, verification **1.802 s** | `baseline/commands.json` |
| Final complete source suite in clean locked release environment | **307 passed in 68.73 s**, no failures or skips; command wall time **69.957 s** | `final-validation/pytest.txt`, `.xml`, `pytest-command.json` |
| Independent runtime probes | **37/37 passed** after fixes; original failures retained | `geometry/RUNTIME_INDEPENDENT_REVIEW.md` |
| Fresh installed wheel, outside editable/source imports | **9/9 passed in 37.7904 s**, plus verification after snapshot | `final-release-build/summary.json`, `installed-wheel-final/commands.json` |
| Reimported analytic STEP cuts | **3/3 fixtures; 16,320/16,320 requested ordinates accounted for** | `geometry/analytic-step-audit/report.json` |
| Actual browser and offline snapshot | **34/34 passed**: authenticated API/UI, source/model rendering, blocked upload, mobile layout, review history, keyboard/labels/error recovery and offline rendering; no JavaScript exceptions | `browser/report.json`, `browser/KEYBOARD_QA.md`; original unnamed-dialog failure retained |
| Final integrity sweep | **35/50 valid**: 32 blocked benchmark records and all three successful CAD records. **15 blocked benchmark records denied** because old staging/reservation state coexists with final records. | `final-validation/integrity-sweep.json`, `evidence/final-replay-publication-investigation.json` |
| Frozen OCR/mock diagnostic | 13 cells; results below | `provider/mock-comparison-v2-final.json` |

The final source command used `PYTHONPATH=src`, `PYTHONDONTWRITEBYTECODE=1` and
one native numerical thread. The installed smoke used an isolated interpreter
with `-I` outside source imports. Its nine checks cover installed import/assets,
`pip check`, CLI help, generated example, real reconstruction, verification,
immutable review, verification after review and portable snapshot creation.

The exact tested wheel is `vessel_reconstruction-0.2.0-py3-none-any.whl`,
115,584 bytes, SHA-256:

```text
5c9e91a2e29bddcb45c0913ce8beefffefae13360ef95cc815d0c81533d89070
```

All **19 Python modules** matched between wheel, installed package, current source
and implementation captured in the successful run. All **three web assets**
also matched the wheel, installed package and source after the final dialog-label fix. The final run has no staging
directory or reservation. Its real 21-section CAD reconstruction took **35.6037 s**;
the STEP is **7,456,513 bytes**, and its standalone snapshot **13,489,497 bytes**.
These are measured execution examples, not a throughput guarantee.

### Clean installation and preserved failed attempt

The first working environment had duplicate old/new dependency metadata after
patch updates and failed `pip check`; it was not relabeled clean. A new environment
was created without bootstrap pip and populated from the hash-pinned wheelhouse.
It had **55 exact distributions, no duplicate distributions, 55 matching wheel
hashes, and 10,315 verified RECORD-hashed files totaling 1,411,692,344 bytes**.
Another 4,408 unhashed entries were counted separately. `pip check` passed.
The lock SHA-256 is
`c174783edee6191f9a0e44676b64262e1ebbef66c8ecb419a16aa3f49c73666c`.

The first installed native run in that clean environment produced an inconsistent
state: a sealed final directory coexisted with an older staging copy and a live
reservation. Verification denied exports, and recovery refused the ambiguous
combination. An exclusive instrumented repetition showed correct checkpoint,
rename, durability and reservation removal; it also recorded an ephemeral receipt
reappearing after deletion. The mechanism remains **unresolved**. A subsequent
fresh, uninstrumented installed-wheel smoke passed completely. No gate was weakened
and no failed output was manually relabeled. See
`evidence/INSTALLED_PUBLICATION_INVESTIGATION.md`. The final exact-source replay subsequently showed the same class of inconsistency
in **15 of 47** blocked benchmark records: old `section_extraction` reservations
and matching staging directories coexist with sealed final records. All declared
final file bytes still match their recorded hashes, but **verification correctly
refuses admission**. The other 32 benchmark records and all three successful CAD
runs verify. The earlier CLI receipts reported blocked outcomes; the later sweep
is separately retained and takes precedence over any implication that all final
records remain admissible. The cause is still undiagnosed. No stale state was
deleted to improve the score. See
`evidence/final-replay-publication-investigation.json`. These observations are a
blocker to claiming unattended operational reliability.

## Geometry proof and its limits

The baseline narrow-peak fixture has a true 6 m beam and 81.25 m³ piecewise-linear
volume. Uniform resampling produced 2 m and 80 m³, with **2 m maximum local loss**.
The revised CAD preserves 6 m and 81.25 m³.

The independent comparator cuts the **exported and reimported STEP**, including
terminal closures, observed stations and every bay midpoint. It compares original
knots, CAD cut vertices and 1,025 dense heights against an explicit analytic ruled
reference, accounting for every requested ordinate.

| Analytic fixture | Maximum station error | Maximum midpoint error | Relative volume error |
| --- | ---: | ---: | ---: |
| Off-grid narrow peak | 8.793 × 10⁻¹³ m | 2.220 × 10⁻¹⁶ m | 0% |
| Chines, unequal heights/counts, zero/finite keels | 2.854 × 10⁻¹² m | 1.474 × 10⁻¹³ m | 9.127 × 10⁻¹³% |
| Smooth unequal sampling | **0.879 mm** | **0.732 mm** | **0.0391%** |

The **1 mm bound is CAD approximation to the observed polyline**, measured in
half-breadth at matched heights. It is not a millimetre-accuracy claim for an image,
a physical hull, unknown between-station shape or the tessellated STL. Separate
STL deflection reached 14.55 mm in the larger assisted example. The system limits
correspondence to 513 common knots, 20,000 estimated faces, 300 stations and 1,025
source points per station, blocking excessive work rather than silently coarsening.

## Historical replay: a material completion regression

The exact original input manifest was checked:
`67230410b389d46fbd3d02be94db7dd1122372d4ff89bb716b8bf5d0ca79381b`.
All **47** cases were rerun with one job at a time against the final source
snapshot in the clean release environment. All **19 Python modules** match the
release source. The run took **124.125 s**: CLI/result statuses for all 42 numeric
cases were **blocked**, with no `failed` status, and all five expected blocking
cases passed the evaluator. A later integrity sweep denied 15 of the 47 records
because old reservations/staging reappeared alongside final evidence; this is an
unresolved publication failure, not a successful verification of those records. The longest
case took **21.100 s**. The evaluator timeout was explicitly increased from the
old 90 s setting to 195 s to accommodate a bounded 180 s worker; all cases still
finished below the old limit, so this change did not alter observed outcomes.
See `confirmation-replay-final/report.json` and
`final-release-build/final-replay-summary.json`. This is known regression material,
not an unseen test. The historical challenge is an insufficient-input block,
not an authentic-scan reconstruction.

The earlier replay remains separately preserved. It used an earlier hardening
code snapshot (seven modules differ from the final release) and the working
environment with the documented Pillow metadata anomaly. Its 42 numeric cases
ended as 41 blocked and one failed (`evidence_commit_failed`); all retained
contour ambiguity. Its captured implementation is retained with its report.
The final replay does not rewrite that earlier outcome.

| Category | Earlier report, not a new base rerun | Current unassisted replay |
| --- | ---: | ---: |
| Clean synthetic | 20/20 numeric completions | **0/20** |
| Degraded synthetic | 17/20 numeric completions | **0/20** |
| External CAD rasterizations | 2/2 numeric completions | **0/2** |
| Expected blocking cases | 5/5 correct blocks | **5/5 evaluator blocks** |

These are evaluator outcome counts. The independent post-run integrity check
found **32/47 normally verified blocked publications and 15/47 publication-admission
failures**, as described above. No numerical model was exported in either group.

The drawings contain undeclared full-height pale vertical grid strokes. Retaining
plausible strokes across contrast bands makes those lines compete with the hull.
Darkness alone is no longer accepted as physical identity. This closes the
demonstrated faint-original/dark-annotation acceptance hole, while exposing missing
semantic information. It is a practical usability regression, not a passing
scientific benchmark. Short, faint and nearly overlapping alternatives can still
evade heuristics; the detector is not a proof of unique contour identity.

The simple pixel baseline was also scored on the frozen inputs. Mean volume error
was **0.4091% clean**, **0.7212% degraded**, and **0.9039% external**. Current
unassisted reconstruction produced no numerical output on those cases, so no
current aggregate accuracy advantage is claimed. The earlier main method's
historical clean mean was about 1.064%, already worse than the simple baseline on
that metric. Clean/degraded pairs share 20 geometries; the two external views share
one cropped, mirrored and capped DTMB hull.

### Two explicitly assisted known cases

A source-only utility generated coarse pixel corridors from the unchanged PNG
and calibration: luminance threshold 128, anchor approximation 2 pixels, corridor
half-width 6 pixels. No target offsets, reference geometry or prior reconstructed
curves were used to propose anchors. The assistant visually inspected all 66
panels. This is **AI/pixel assistance**, not human expert adjudication. The source
threshold can itself choose the wrong dark line; this proposal utility is never
silently invoked after abstention.

The multichine case used 115 anchors over 25 stations; DTMB used 342 over 41.
Generation took 0.139 s and 0.284 s respectively. Those are compute times;
**human correction effort was not measured**. Original calibration, initial
proposal settings and scoring gates were preserved. The initial assisted
multichine attempt blocked, revealing that clipping a wide horizontal ruler could
turn it into a local stroke. A generic pre-clipping rejection fix, with an
independent zero-keel regression, resolved this without changing the anchors.
All attempts are retained. Evaluator labels were decoded after final inference.

| Known case | Volume error | Observed-section RMS | Maximum sampled observed-section error | CAD fit to observed curve | Worker time / peak RSS |
| --- | ---: | ---: | ---: | ---: | --- |
| Synthetic multichine | **1.047842%** | 24.847 mm | **153.491 mm** | 0.982180 mm | 39.148 s / 1,187,496 KiB |
| External DTMB raster | **0.975280%** | 2.822 mm | **32.860 mm** | 0.998835 mm | 64.817 s / 1,494,916 KiB |

Both produced valid single solids and met the reused volume/RMS gates. The observed
shape errors are sampled at 257 heights per station; these are not additional
independent STEP-cut audits. Neither is an authentic paper scan. Neither replaces
the unassisted denominator, estimates unseen performance or receives engineering
approval. See `geometry/assisted-regression/report.json` and its workflow notes.

## OCR, optional models and data rights

No new neural model was trained. Existing Tesseract weights provide OCR. The
optional model adapter only creates bounded, source-bound proposals; it cannot
set accepted observations or feed CAD automatically. It checks exact source hash,
page, pixel rectangle, units, raw token and deterministic unit conversion. Printed
instructions are untrusted data. Models receive no tools. The adapter rejects
redirects, malformed/oversized responses and unbounded usage fields, serializes
budget reservations, and retains attempted-call evidence on errors.

The frozen diagnostic has 13 generated cells and no external drawings. Version 2
uses opaque crop hashes as identifiers. A review found that earlier descriptive
IDs could leak class hints; the original mock evidence was retained, the live
path was corrected, and **no live call had occurred**. Inputs are captured with
bounded, no-follow directory access and verified before any possible network
call. Live use requires authorization for the exact dataset manifest hash and an
explicit cash ceiling. Targets are decoded by scoring after responses, never
supplied to the live adapter. Partial failures checkpoint evidence and abstain
on the remaining cells.

| Diagnostic method | Emitted | Exact among emitted | Wrong among emitted | Abstained |
| --- | ---: | ---: | ---: | ---: |
| Tesseract, two configurations | 6/13 | 6 | 0 | 7 |
| Scripted model mock | 6/13 | 5 | **1 deliberately wrong** | 7 |
| Exact OCR/mock agreement | 5/13 | 5 | 0 | 8 |

These numbers test proposal validation and selective-risk accounting; they do
**not** measure DeepSeek, VLM quality or unseen OCR accuracy. No proposal entered
geometry. Manual correction time, live-model nondeterminism and geometry-level
benefit remain unmeasured. See [optional model instructions](OPTIONAL_MODELS.md).

The second line of the supplied credential file was used only in a read-only
public OpenCode Go catalog request, which returned HTTP 200. That endpoint does
not establish credential/subscription validity. **Zero generation calls, zero
model crop transfers and zero inference charges were incurred by this work.**
Go may overflow to paid credits; no cash budget or overflow authorization was
provided. Current provider claims, dated pricing, limits and expiry are recorded
separately. There is executable live scaffolding but no live performance result.

The historical Balclutha curve trace and table attempt remain failed/blocked
evidence from the earlier work. There is no new completed authentic archival
reconstruction or qualified expert label set. Original DTMB, OCR weights and
archival notices have separate rights scopes. No new third-party scans or weights
were added to Git or sent for model processing. The new release's diagnostic
images are procedurally generated.

## Contracts, operation and migration

1. A validated request enters a bounded durable queue before bytes are spooled.
   Input and specification hashes are checked again before an isolated worker runs.
2. The worker preflights all sources, extracts evidence, constructs bounded CAD and
   checks it. Its process profile bounds wall time, CPU, address space, output and
   file size; cancellation kills the ordinary process group. Native threads are
   restricted and provider credentials are excluded from its environment.
3. A private reserved transaction assembles the immutable schema-2 record and
   manifest. Publication is atomic and no-replace on the same Linux filesystem;
   admissibility also requires durability and reservation cleanup. Recovery
   quarantines partial geometry and conservatively refuses ambiguous state.
4. API/CLI verification checks the complete inventory and derived consistency.
   The API additionally requires a compatible durable terminal job state before
   serving a model. A complete publication followed by a late worker failure may
   be reconciled only after full verification, retaining the original worker
   outcome. Quota violations never become reconciled successes.
5. Review events are separate, locally chained and bound to the immutable run.
   Corrections are new specifications and runs. The workbench exposes replay
   download and candidate overlays; a rich revision-lineage editor is deferred.

Defaults include one active worker, four pending/active slots, a 180 s wall/120 s
CPU budget, 4 GiB process address space, 256 MiB output budget, 2 GiB local storage
quota and a 256 MiB free-space reserve. See [operations](OPERATIONS.md) for all
limits, retention, health, backup and recovery commands. Direct synchronous Python
API callers remain responsible for invoking an isolated worker.

Schema-1 records are recognized as `legacy_unsealed`; they are never silently
upgraded into stronger assurance. Preserve the old directory and reconstruct from
retained source into a new run. Back up the quiescent job database and complete
artifact root together. Rollback uses the base source and a separate compatible
artifact root; do not rewrite sealed runs or reverse-migrate the live database.
See [CONTRACT.md](../CONTRACT.md) for full migration semantics.

The process boundary is **resource isolation, not a filesystem/network sandbox**.
It does not establish arbitrary-native-code containment, cgroup-wide accounting,
multi-user isolation, remote identity, TLS, long-duration availability or power-loss
resilience. Local reviewer names remain unverified. Backup tests are not an off-site
disaster-recovery exercise.

## Dependency, license and release decisions

The exact hash-pinned environment and CycloneDX inventory are new; the original
`requirements-lock.txt` remains historical. The initial OSV scan led to patched
msgpack, multidict, Pillow and PyMuPDF versions. **VTK 9.3.1 still has three known
GLTF-loader advisories**, because the exercised OCP version requires that exact
VTK. Unsupported GLTF/GLB/VTK inputs are rejected before native decode. Exact
advisory/version scope exclusions expire for review on 7 December 2026; they are
mitigations, not repaired dependencies or a security clearance.

PyMuPDF remains optional and dual AGPL/commercial. The repository remains all
rights reserved. Distribution/hosting obligations need an owner/legal decision;
no license was changed or purchased. An SBOM cannot decide that question.
System packages and all embedded native components are not byte-pinned or fully
audited. See [dependencies and rights](DEPENDENCIES_AND_RIGHTS.md).

The release preserves the exact tested wheel, a patch against the exact base,
the new generated diagnostic set and a curated evidence inventory. It excludes
credentials, virtual environments, original archival scans and the old large
research dataset tree. The portable example is a synthetic development model,
with source evidence and review status, not an approved vessel design.

## Readiness assessment

| Intended use | Evidence-supported status | Remaining boundary |
| --- | --- | --- |
| **Local research tool** | **Supported for supervised Linux use within the declared input contract.** Offline reconstruction, inspection, bounded workers and verified exports were executed. | Input semantics and calibration require review; conservative abstention can prevent useful reconstruction. |
| **Controlled pilot** | Foundation implemented; operational readiness is **not yet established**. | Investigate the unresolved publication episodes (including 15/47 replay records); obtain permitted representative real drawings and expert traces; measure correction effort and false acceptance; qualify backup/retention and dependency/license decisions. |
| **Authenticated remote service** | **Not implemented or validated.** Only authenticated local sessions are supported and remote bind is refused. | Remote identity/authorization, TLS, tenant/filesystem/network isolation, aggregate resource accounting and operational testing. |
| **Engineering-qualified use** | **Not established.** All outputs require review. | Independent source/calibration validation, engineering-approved interpretation and tolerances, structural/as-built scope and professional acceptance. |

The highest-value next work is a permitted, expert-annotated set of genuine
overlapping/scanned plans, with explicit grid/contour semantics and measured
operator correction effort. Freeze that split before tuning. The current
analytic geometry proof is strong enough to locate much of the remaining risk
in source interpretation and operational qualification, while retaining the
specific tested limits of the CAD construction itself.
