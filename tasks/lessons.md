# MarinaFrame lessons

### Ask the person when a worker stops making progress
- **Date:** 2026-11-10
- **Trigger:** A loaded laptop's 72-station Gunnerus build was stopped at the 600-second wall limit twice. The founder rejected fixed total time limits for slower laptops.
- **Rule:** Track completed work with an increasing counter. A periodic heartbeat must not increase it. After five minutes without new progress, keep the worker alive and offer Keep waiting or Stop. Default the optional absolute safety cap to off; retain CPU, memory and receipt checks.
- **Why:** Elapsed time depends on machine load. A slow build can still make progress.
- **Security correction (2026-11-10):** Sandboxed model-code children are untrusted. Read telemetry through non-blocking, no-follow descriptors, require a regular file and validate bounded JSON fields. Trusted supervisors count stage/part changes with a finite advance budget; never trust a child's counter. Keep a four-hour security cap for these children only, with a clear error and no automatic retry. Deterministic own-code CAD retains no default total wall limit.
- **Own-code correction (2026-11-10):** Apply the trust policy in every supervisor, including standalone and nested Python CAD. A deterministic kernel call with no part changes must only report a stall and keep running. Report natural section, mesh-face, format and part boundaries; never advance on a timer. Pass the specific stage and duration from supervision into recovery instead of replacing it with the generic publication message.
- **CPU correction (2026-11-10):** Do not apply CPU-time limits to deterministic CAD by default; preserve sandbox limits and report the stopping limit with progress.
- **Cleanup correction (2026-11-10):** A zombie leader does not prove its process group is empty. After a refused group signal on macOS, check for live group members, retry SIGKILL within a fixed bound, and raise if cleanup remains unproven. Keep the leader unreaped until that check succeeds.

### Freeze executable and Python source for concurrent evaluation
- **Date:** 2026-11-08
- **Trigger:** W11 `make test-full` rebuilt `target/release/marinaframe` while a live benchmark used it. The controller correctly stopped at `controller_binary_changed`. The smoke target also lacked `--worker-source`, so its cleared environment could use the main checkout's editable Python install.
- **Rule:** Copy the evaluation executable to `work/` before starting batches and point every arm at that immutable copy. Freeze the Python worker source too. Always pass `--worker-source` for worktree runs, including smoke. Do not rebuild or clean an executable used by active runs. Keep interrupted attempts and their usage; label retries separately.
- **Why:** A git commit label does not pin executable bytes or the source imported by an editable Python installation.
- **W20a correction (2026-11-08):** `run_round.py` resolves `--worker-python`; a venv Python symlink then becomes the base interpreter and loses NumPy/Pillow. Preserve the absolute venv executable path without resolving its final symlink, or pass a frozen executable wrapper that invokes the venv Python. Confirm a worker initializes before spending model requests.

### Keep source stable during pinned worker tests
- **Date:** 2026-11-08
- **Trigger:** W12 CAD finalization tests failed with `worker_implementation_changed` while another step edited or mutated `llm_setup.py`.
- **Rule:** Finish Python edits and restore mutations before starting a task or CAD integration test. Do not edit any Python module until that task ends. Re-run on stable source; do not weaken the implementation identity check.
- **Why:** `provenance.implementation_identity` hashes every Python module in the worker package, including modules outside the tested operation.

### Separate supplied calibration from independent model measurements
- **Date:** 2026-11-08
- **Trigger:** W14 combined half-breadth and grid-scale questions in one request. The breadth question supplied the scale that the scale question was meant to measure.
- **Rule:** Ask independent scale questions in separate requests without supplied scale. Exclude contaminated answers, retain their usage, and keep planned case denominators fixed when a driver fails. State which crop, axes and scale are caller-supplied.
- **Why:** A model can copy supplied calibration without reading the grid; returned-only denominators also hide missing measurements.

### Refuse mixed strokes without erasing review alternatives
- **Date:** 2026-11-08
- **Trigger:** The sysser45 identity fix first removed all sustained ruler overlaps. It promoted formerly ambiguous sole candidates and broke real-CAD tests that require an explicit complete-ruler alternative.
- **Rule:** Keep competing source evidence before refusal. Reject the mixed ruler/hull path, not every complete ruler hypothesis. Preserve explicit operator alternatives and check both policy selection and real-CAD revision tests. Count source-complete reads separately from controller builds and correct builds.
- **Why:** Removing a candidate changes selection authority; it can silently promote another trace or remove a valid review operation even when the main wrong build abstains.

### Reach the forbidden operation in sandbox tests
- **Date:** 2026-11-08
- **Trigger:** W13 file/network tests first passed on Python import-path denial; socket construction was also mistaken for a network operation.
- **Rule:** Use isolated Python for direct OS probes, require the expected forbidden-operation failure, and mutation-check the exact file or network permission. Test bind/connect, not only socket construction.
- **Why:** An earlier permission error can hide a missing guard; Seatbelt permits socket construction without permitting network use.
- **Artifact correction (2026-11-12):** Landlock target checks protect the worker, not later unsandboxed artifact consumers. Deny model-created symlinks (MAKE_SYM) unless every host consumer opens all path components and the final regular file through no-follow descriptors. Test a trusted pre-existing symlink for target escape separately from model symlink-creation denial.

### Repartitioned holdouts are hull-disjoint, not family-disjoint
- **Date:** 2026-11-08
- **Trigger:** All original Ship-D clusters were already represented; a new seed cannot establish independence from those broad families.
- **Rule:** Name the approved replacement split “hull-disjoint (v2)” in manifests, README and scorer output. State that clusters can share broad families with frozen splits. Exclude every new cluster containing any previously rendered hull. Keep the truth sealed; run no reader or scorer during generation or development. Score only at frozen checkpoints.
- **Why:** New partition labels do not prove new hull families.
- **Performance correction (2026-11-12):** The performance protocol printed JBC measurements and its draft unit tests used JBC open-water truth before code was frozen. A later frozen one-shot run cannot restore blindness. Keep blind measurements with an independent evaluator, never use them as development fixtures, and report exposed cases as non-blind. Ask the PM for a fresh public split; do not substitute restricted holdouts. PM decision: JBC becomes development and a separate evaluator owns the blind check. Inventory all prior per-ship file/value exposure before more reads; use only already-exposed measured-data ships for development and leave every unexposed ship's test data unopened for evaluator selection.

### Count plan crossings before combining scan columns
- **Date:** 2026-11-08
- **Trigger:** W15 review found that taking the darkest pixel across a three-column strip merged two diagonal waterline crossings into one run and accepted an anchor on white station-column pixels.
- **Rule:** Count ink runs separately in each scan column. Refuse any competing crossing, and measure the accepted anchor on the actual station column. Test diagonal competitors as well as separated horizontal strokes.
- **Why:** A union of neighbouring pixels loses stroke multiplicity; apparent strip continuity does not establish unique station-column evidence.

### Use small CAD-first development rounds
- **Date:** 2026-11-08
- **Trigger:** W17's large campaign repeated the same blocked draft build after investigation already succeeded; the PM stopped it after four after-change cases.
- **Rule:** Test DTMB L0-L3 first, inspect every trace, and fix the first common blocker. Stop early when the first two cases repeat the prior blocker. Run 24 development cases only after at least three of four produce STEP drafts. In draft mode prioritize usable CAD with cheap warning labels and open guesses; keep strict mode and the frozen 2% RMS/5% volume gate unchanged.
- **Why:** More instances of the same failure spend tokens without testing a new hypothesis; draft evidence defects must not discard otherwise usable CAD.
### Progress before provenance (MarinaFrame)
- **Date:** 2026-11-08
- **Trigger:** I designed W18 memory with heavy provenance (controller-only summaries, id checks, byte replay tests). The founder said: do not be obsessed with provenance; get the model producing workable CAD first, line-by-line evidence later.
- **Rule:** For the LLM investigator, optimise for built and gate-correct drafts first. Keep only cheap safety labels (unverified draft, open guesses, engineering_approved=false, fixed scoring gate). Defer provenance machinery that does not help the model build a draft, and relax tool evidence rules in draft mode when they block progress.
- **Why:** Evidence rules added before the model could build anything blocked all progress (270 of 288 no_progress).

### Iterate on a few cases before any campaign (MarinaFrame)
- **Date:** 2026-11-08
- **Trigger:** The 288-case head-to-head and the 24-case W17 baseline spent hours and tokens mostly on one repeated failure (`no_progress` loops). The founder called it a huge waste with no useful data for making the model work better.
- **Rule:** Before scaling an LLM run, run 2-4 cases, read every trace, fix the first blocker, and repeat. Stop a round early when the first cases fail the same way as before. Run larger sets only when a small round mostly succeeds or shows varied failures; keep sealed runs for frozen checkpoints only.
- **Why:** A uniform failure is visible in 2 traces; more cases add cost, not information.

### MarinaFrame's agent fills gaps; it does not stop (product principle)
- **Date:** 2026-11-08
- **Trigger:** My W17b brief still treated missing or bad drawing data as a reason to refuse or only interpolate geometrically. The founder said the point of an agentic MarinaFrame is to use AI to fill in what is not in the data, not to stop when data is missing or bad.
- **Rule:** In draft mode, design every missing-data path so the model infers the missing part (section shape, scale, stations, principal dimensions) and code builds and labels it (`traced`, `repaired`, `interpolated`, `ai_inferred`). Stop only when no solid can be made at all. Keep the labels, `engineering_approved=false` and the fixed scoring gate.
- **Why:** Earlier evidence-only rules (model never writes geometry, refuse on gaps) made the product deliver nothing on imperfect drawings, which are the normal case.

### The model writes geometry (MarinaFrame, supersedes "model chooses WHAT, code measures HOW MUCH")
- **Date:** 2026-11-08
- **Trigger:** I described the old rule "the model must never write geometry" as a draft-mode exception only. The founder said writing geometry is half the point of the model.
- **Rule:** Treat model-authored geometry (sections, waterlines, sheet values, corrections of traces) as a main path. Code fairs, sanity-checks, builds, renders back and labels the source of each section; the frozen scoring gate measures quality. Do not design tools or prompts that forbid the model from writing geometry.
- **Why:** The earlier evidence-only framing made the model a selector of traced ink; on imperfect drawings that delivers nothing.

### Happy path first; do not add failure paths (MarinaFrame)
- **Date:** 2026-11-08
- **Trigger:** W17c added a new build failure (`authored_outside_draft`) and I proposed more checks. The founder said: stop making builds fail; focus on happy paths first.
- **Rule:** Until the model reliably produces drafts, do not add refusals or blocked states. In draft mode, turn checks into warnings whenever a solid can be made. Spend effort on read -> geometry -> build -> render -> finish.
- **Why:** Every gate added before the main path works produces more empty results and no learning.

### Watch disk space when many lanes build CAD (MarinaFrame)
- **Date:** 2026-11-08
- **Trigger:** With 4-6 parallel lanes, the disk filled (ENOSPC, 154 MB free) and the first-hull lane stopped mid-measurement. Each worktree keeps its own Rust `target/` (1-7.5 GB) and CAD runs keep build folders.
- **Rule:** Remove a worktree (after checking `git status --short --ignored` and copying ignored data) as soon as its branch is merged. Tell measurement lanes to delete per-case build folders after scoring and keep new data under ~3 GB. Keep a disk check (stop and warn below ~6 GB free) in the lane watcher.
- **Why:** Rebuildable build output in finished worktrees took 19 GB that live lanes needed.

### Cap CPU-heavy parallel work at the core count (MarinaFrame)
- **Date:** 2026-11-08
- **Trigger:** On a 10-core Mac (4 performance, 6 efficiency) the load average reached 22-26: one lane ran 5 measurement shards, another scored many perturbed hulls, and Sol ran rounds and `make test-full`. CAD builds then hit worker wall-time limits and silently dropped stations, so results depended on load (00045-L2: 4.56 % alone, 14.87 % under load).
- **Rule:** Keep at most about 8 CPU-heavy processes across all lanes: measurement lanes run at most 2 cases at a time, one `make test-full` at a time. Recheck any regression by rerunning the case alone before trusting it.
- **Why:** The admission lock covers controller runs, but evaluation scripts bypass it.
- **W20a correction (2026-11-08):** Read-phase panels with one scale are one view family; reuse the first setup and preserve panel-specific datums. Repair malformed description/envelope fields, coerce usable numbers and retain the rest as metadata with warnings. Unknown off-sheet dimensions stay null with a warning; incomplete waterline sets must also warn. Do not spend requests repeating harmless shape failures.

### Optimise for accuracy and coverage, not model cost (MarinaFrame)
- **Date:** 2026-11-08
- **Trigger:** I reported cost per case as a main result and wrote "keep it cheap" into briefs and designs. The founder said model cost is a tiny fraction of a naval architect's time; what matters is accuracy and how much ground the tool helps them cover.
- **Rule:** Treat model cost as a minor constraint. Prefer the option that gives more correct drafts and more drawings covered (thinking on, more requests, more passes, stronger models, ensembles) when it measurably helps. Still report cost, but do not trade accuracy for it. Wasted runs that teach nothing are still waste (time, not money).
- **Why:** The value is the naval architect's hours saved, which dwarfs API cost.

### Read light lines against the paper beside them (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** On blurred L1 sheets the dash-dot body-plan centreline and light grid and station lines were missed: the detectors used one sheet-wide ink level and one unbroken run, so the centreline fell back to a grid or hull line (series60-3v-L1: 119 px off) and three station lines vanished (shipd-1-08158-3v-L1).
- **Rule:** Detect drawn lines by local contrast (`ndimage.grey_closing` across the line minus the pixel) and by inked share along the line, not by a global threshold or the longest run. Keep the old detector beside it where a dark line that ink widens must still be found (baseline). Check each detector change on every dev sheet L0-L3 against truth datums before a live run.
- **Why:** Sheet-wide levels fail on grey, uneven, blurred scans; a dashed datum line has no long run.

### Replay a live round before spending another (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** A reader change helped one case and broke another (shipd-1-09867-3v-L0: the intake's half-width profile region, 3.4 -> 19 %); only a replay of all ten earlier live readings showed it.
- **Rule:** After each reader change, replay the model's earlier phase-1 readings through `build_first_hull` (copy the task's `domain/input` and the reading state, re-run `_describe_vessel` on `model_description`, score the first-hull STEP) for every L0 and L1 dev case. Run live rounds only after the replay shows no regression.
- **Why:** Live runs vary by 1-5 points from the model alone; replays isolate the code change.

### Push only after the checks pass in the same command
- **Date:** 2026-11-09
- **Trigger:** After a merge, `make test-quick` failed (a stale `marinaframe-app-core` build cache made lint report missing methods), but the same shell line pushed anyway because the push was not chained to the test result. The code was fine; `cargo clean -p marinaframe-app-core` and a rerun passed.
- **Rule:** Chain the push to the check: `make test-quick && git push ...`. If the check output goes through a pipe (`| tail`), run `set -o pipefail` first: without it the chain sees `tail`'s exit code and pushes after a failure (it happened twice on 2026-11-09). If a Rust error names a symbol that exists in the source after a merge, clean that package and rerun before changing code.
- **Recurrence (2026-11-09, evening):** `git merge ... | tail -1 && set -o pipefail && ...` hid a merge conflict, ran the tests on a half-merged tree and force-removed the worktree. `set -o pipefail` must be the first command of the line, before the merge step too; never pipe `git merge` output.
- **Why:** An unchained push can publish a state that the checks did not pass.

### Score the delivered build, not the state you meant to keep (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** Best-of-2 readings kept the better first hull in the task state (dtmb5415-3v-L0: 13.8 % against 32.6 %), but `build_draft` then reused the set-aside reading's build because build reuse matches generation and revision ids, which do not name the materialized setup. The digest scored 32.6 %.
- **Rule:** When task state is swapped or restored (a new reading, a rebuilt setup), move the replaced builds out of `builds` (history only) so no later build can reuse them. After a selection change, score every valid build of a live case (`score_builds` pattern) and check that the digest's scored STEP is the one the state names.
- **Why:** Reuse keys and delivery paths are separate from the state a selection writes; a correct selection can still deliver the wrong hull.

### Measure a model's image limit before you size images for it (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** The plan for Claude Sonnet 5.5 assumed Claude downsamples images above about 1,568 px. A token probe through the `claude` CLI (`work/claude-vision-probe`) showed image tokens growing with the area up to about 3.75 Mpx (2,048^2 and 2,576^2 both 4,809 tokens) and 9 px text readable at 2,048 px, so a 1,568 px cap would have thrown away detail.
- **Rule:** Before a per-model image cap, send square and wide test images of several sizes and read the input-token count: a flat count marks the downsampling size. Also read small text at each size. Record the numbers beside the model's entry in `rust-control/src/models.rs`.
- **Why:** Published limits change between model generations; the token count is the model's own statement of what it received.

### Explode DXF blocks before reading construction labels (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** The Gunnerus shell expansion and profile-and-plan sheets showed dozens of `PL` labels in the PDF, but a model-space text scan found almost none: the drawings sit in anonymous `A$C...` blocks, and plate thicknesses are `ATTRIB` values (tag `XX.X`) of `PLDIM2` inserts.
- **Rule:** Read DXF construction sheets with `ezdxf.disassemble.recursive_decompose` (positions in world coordinates) and classify labels by attribute tag (`XX.X` plate, `FL.ST` flat bar). Compare the found label count with the rendered PDF before concluding a value is not printed.
- **Why:** Round 2 reported Gunnerus plate thickness as not printed; round 3 found 77 % of the steel weight printed once blocks were exploded.

### Check the body-plan side assignment twice before a holdout protocol (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** Round 13 (BUMBLE BEE 47): the operator agent read the station labels and set the forebody (1-6) left and the aftbody (7-14) right; the chains fit the opposite halves within 2-6 mm. Code misnamed 10 of 14 stations and the models could not fix it, because each half's candidate stations were wrong. The round had to be reported as run.
- **Rule:** Before a holdout protocol commit, have a second, independent check of which half is bow and which is stern (a different agent reading the labels in its own crops, or the profile's stem/stern position against the body plan), and record both readings in the protocol. If they disagree, stop and resolve before any run.
- **Why:** One agent's reading of small station labels is a single point of failure, and a side swap turns a good reading into a systematic naming error that no later step can see.
- **Recurrence (2026-11-11, Cama Beach published holdout):** the sides were checked twice and agreed, but the truth-blind calibration named every curve one station off on both halves (the printed station number was the drawn label minus one; the heavy "transom" line was station 10). The one-run holdout failed mostly on this. Rule addition: the second check must also confirm station identity, not only sides: match each body-plan curve to a station position in the profile or half-breadth plan (x along the hull) and to the station count in the table header, and record that match in the protocol before any run.

### A wait loop must not match itself (MarinaFrame)
- **Date:** 2026-11-09
- **Trigger:** `until ! pgrep -f "replay_edits" ...` waited forever: the waiter's own command line contained the pattern.
- **Rule:** Wait on a PID (`kill -0 $pid`), a result-file count, or a done marker, not on `pgrep -f` with a pattern that the waiting command contains.
- **Why:** Silent waits hide finished work and block the lane.

### Commit a lane's measurement scripts before removing its worktree (MarinaFrame)
- **Date:** 2026-11-10
- **Trigger:** The best-of-N lane validated its fit score offline on 130 stored drafts with a script that lived only in its worktree. I removed the worktree after the merge (`git worktree remove --force`), so a later lane (better picks) could not rerun the validation and had to rebuild it from the doc.
- **Rule:** Before removing a merged worktree, check `git status` there for untracked scripts, benchmarks or replay tools; commit any that produced a reported number (data stays in git-ignored work/), or ask the lane to. Do not use `--force` while untracked code files remain.
- **Why:** A number in a doc that cannot be reproduced cannot be compared with later work.

### Keep per-run replay data out of commits (MarinaFrame)
- **Date:** 2026-11-10
- **Trigger:** Cross-view outlier replay wrote a 5.2 MB derived JSON file under `outputs/`; the user asked to move it to ignored `work/` before committing.
- **Rule:** Write per-run derived replay JSON and logs to git-ignored `work/`, including the script's default output path. Commit the replay code, tests and concise result tables, not the per-run data.
- **Why:** Reproducible measurement output is not a source deliverable and need not enlarge repository history.

### Keep run accounting data in work and include intake calls
- **Date:** 2026-11-10
- **Trigger:** Cost-per-ship ledgers were placed in outputs, and the initial collector omitted the live hull intake calibration log.
- **Rule:** Keep per-run derived JSON/CSV ledgers in git-ignored work/; commit the accounting script, tests and dated report only. Count intake calibration receipts as well as controller receipts. The calibration log's input_tokens already includes cache reads and writes, so preserve it as collapsed prompt usage and price it with a range. Do not add intake time again to inclusive case wall time.
- **Why:** Generated run data does not belong in source history, and omitted or misclassified calibration usage understates the hull cost.
### Keep sheet replacement separate from source classification
- **Date:** 2026-11-10
- **Trigger:** Recovery must accept a clearer scan without discarding the old draft or reusing its old pixel reading.
- **Rule:** Keep source versions and dependent output state in the run. Record a uniform resolution adjustment explicitly; require new calibration for a changed page shape. Keep unrelated outputs. Leave independent checks not run while draft guesses remain open. Test the single-file picker as well as the worker command.
- **Why:** A readable replacement is input for another draft revision, not an engineering review.
### Keep the booklet check as secondary evidence
- **Date:** 2026-11-10
- **Trigger:** The PM set the accuracy rule while reviewing the booklet-check feature, after a competitor report criticised a hydrostatics-only accuracy claim.
- **Rule:** State in the booklet documentation and PDF section that integrated quantities (displacement, LCB, KMT) can agree while local shape is wrong. Keep section-shape error at withheld stations as the primary accuracy number. A booklet match cannot replace a missing shape-error measurement.
- **Why:** Integrated hydrostatics can hide local shape errors that cancel along the hull.

### Check IGES side coverage before reflecting a hull
- **Date:** 2026-11-10
- **Trigger:** The first bounded DSYHS check doubled SYSSER43 volume and waterplane area because that IGES already contained both sides, unlike most files in the archive.
- **Rule:** Inspect side coverage before reflection. A sign crossing at y=0 can be a spline overshoot, not a full hull. For the symmetric DSYHS canoe bodies, require equal port/starboard extents within mesh tolerance before preserving a full hull once. Test half hulls, overshoots and full hulls. Use absolute mesh deflection and a bounded CAD process for imported geometry.
- **Why:** One archive can mix half hulls and full hulls; a file-name convention does not establish geometry coverage.
### Keep inferred fairing stations outside immutable observed-station records
- **Date:** 2026-11-10
- **Trigger:** A three-view fitter could build a valid STEP with new half stations, but inserting them inside `pipeline.reconstruct` would violate the unchanged verifier's exact submitted/observed station-id contract.
- **Rule:** Treat direct CAD validity and immutable run publication as separate checks. Keep new half-station fitting/export explicit until an earlier input-materialization stage declares those stations. Do not weaken the verifier or rewrite submitted station evidence to make the new ids pass.
- **Why:** A valid solid is not sufficient evidence that an application run can be published.

### Freeze reference scale in paired fit trials
- **Date:** 2026-11-10
- **Trigger:** A whole-station injection increased the legacy fairer's measured half-beam, changing its Huber scale and movement tolerance inside a supposedly fixed-scale trial.
- **Rule:** Pass the unperturbed half-beam explicitly to both paired fits, including station-only baselines and missing-view fallbacks. Recompute affected trial measurements; keep the fit/check choice frozen.
- **Why:** Re-estimating a scale from perturbed evidence confounds error response with a parameter change.

### Match CAD export units to STEP
- **Date:** 2026-11-10
- **Trigger:** The CAD export brief said metres, but STEP uses millimetres; the PM corrected the brief so IGES and future .3dm exports match STEP.
- **Rule:** Write IGES and future .3dm exports in millimetres, the same unit as STEP. Set the IGES unit flag to 2 (MM). Keep file labels, export metadata and tests consistent with that unit.
- **Why:** Matching CAD units avoids scale errors between formats; metre-based reporting does not change the CAD file unit.

### Use IGES for surface exchange
- **Date:** 2026-11-10
- **Trigger:** The PM changed IGES export from MSBO solids to trimmed surfaces because many CAD tools import entity 186 unreliably.
- **Rule:** Use IGESControl_Writer mode 0 for trimmed surfaces. Keep STEP as the solid format. Test imported face counts and sew the hull faces into a closed shell; do not require imported IGES solids.
- **Why:** A valid OCC solid round-trip does not prove reliable exchange with other CAD tools.

### Preserve face trims in Rhino exports
- **Date:** 2026-11-10
- **Trigger:** The PM found that exporting a trimmed face's UV-bounded support surface filled areas outside the real deck or transom outline.
- **Rule:** Compare face and support areas. Write planar outer trims as exact Breps. Use and label a counted mesh fallback for non-planar trims and unsupported inner holes. Keep representation counts in document user text and the export return value; test written areas and source bounds.
- **Why:** Correct units and NURBS control data do not preserve a trimmed face's boundary.

### Run the full suite when a lane changes export file lists
- **Date:** 2026-11-10
- **Trigger:** The CAD export lane added IGES and .3dm files; its focused tests passed, but three evidence-hardening tests failed at merge because a test helper copied a fixed file list. A replace-sheet real-worker test also failed in CI because it did not skip without `MARINAFRAME_TEST_PYTHON`.
- **Rule:** When a lane changes run files, export kinds or record checks, run the full Python suite before review, not only focused tests. Test helpers copy the files the record names, not a fixed list. Real-worker Rust tests may skip locally when `MARINAFRAME_TEST_PYTHON` is unset; required CI runs must fail instead.
- **CI correction (2026-11-10):** Allow missing worker Python only in local runs. Required CI jobs set `MARINAFRAME_TEST_PYTHON` before every Cargo test step and `MARINAFRAME_REQUIRE_WORKER=1`; missing Python must fail those tests. Run macOS Seatbelt probes on macOS, and prove cleanup helpers reject a live child before trusting their exit checks.
- **Lane correction (2026-11-12):** Do not stop a behaviour-preserving GA refactor on an unrelated full-tier worker failure when the PM supplies targeted gates. Diagnose once with explicit `MARINAFRAME_TEST_PYTHON` and `RUST_BACKTRACE=1`, report the complete registry error (or `None` on a passing run), then use the PM's GA tests and offline replay gates. Leave the full merge tier to the PM; do not change unrelated tests or app code.
- **Why:** Focused runs miss tests that encode the old file set, and CI's plain cargo step has no worker Python.

### Bind display exports at their producer
- **Date:** 2026-11-10
- **Trigger:** Revision export switched to build-record display keys that no real producer wrote, so packages lost task-level whole-vessel and tank models.
- **Rule:** Trace each actual producer and carry the chosen revision, build identity and file hash from production to export. Test the real producer path as well as revision and hash mismatches; report unbound files instead of assigning them to the current revision.
- **Why:** A fixture that invents record fields can pass while production never supplies them.

### Name plan waterlines by drawing correspondence, not by order (MarinaFrame)
- **Date:** 2026-11-10
- **Trigger:** View reader v2 first named plan-view runs by order from the centreline. On shipd-1-00679 (tumblehome: the deck line is innermost) and shipd-1-08158 (crossing waterlines) identity fell to 15-45 %. Grid-row heights from every long line also gave 14 spurious waterlines on ten sheets.
- **Rule:** Name a plan curve from a cross-view correspondence (its centreline end equals the profile end at its height), follow it, and abstain at bunches, crossings and shared ink. Take waterline heights only from labelled grid rows on the regular spacing. Score evidence against development truth before any fitting.
- **Why:** Breadth order with height is a hull property, not a drawing rule; accurate evidence can still worsen a fit when the fit holds stored boundaries in another datum (section 10.5).

### Pin a new dependency in every lock file
- **Date:** 2026-11-10
- **Trigger:** The CAD export lane added rhino3dm to pyproject.toml and requirements-lock.txt only. CI installs the hashed requirements-linux-py312.lock, so the worker's .3dm export failed with ModuleNotFoundError and the real-CAD Rust tests failed for several pushes; local runs passed because the dev .venv had the package.
- **Rule:** When adding a runtime dependency, add it with hashes to requirements-linux-py312.lock and requirements-worker-macos-arm64-py312.lock as well as pyproject.toml and requirements-lock.txt. Check `git grep -l "^<name>==" -- 'requirements*'` lists all four. A test that fails in CI should print the worker observation, not only "failed".
- **Why:** CI and the packaged worker install only from the hashed locks, not from the dev environment.

### Do not read another vessel's narrative year as a principal particular
- **Date:** 2026-11-10
- **Trigger:** The particulars reader read 1897 from the C.A. Thayer title notes, which say the builder built another vessel in that year. C.A. Thayer's own construction year is 1895.
- **Rule:** Require a labelled construction-year field or explicit vessel identity before accepting a year in prose. Keep the other-vessel sentence as a negative fixture and report missed prose fields in development results.

### Give a sideways-scrolling UI strip explicit room for its scroll bar
- **Date:** 2026-11-11
- **Trigger:** The section strip (`overflow-x: auto`, height from its tiles) showed cut tiles and a vertical scroll bar in the app's WebKit view on a 72-section run. Headless Chromium checks passed, because Chromium adds a horizontal scroll bar to a flex item's height and WebKit does not.
- **Rule:** For a horizontal scroller, style its scroll bar to a fixed height, include that height in the min-height, and set `overflow-y: hidden`. Check long lists (70+ items) on the mock, not only the three-section fixture.
- **Why:** Scroll bar sizing differs between web views and with system scroll bar settings; a layout that depends on it fails only on some machines.

### Do not iterate OCP collections in per-face loops
- **Date:** 2026-11-11
- **Trigger:** The Gunnerus display mesh took 60 to 100 s for 3,151 hull faces, even with the triangulation already built. cProfile misattributed the time.
- **Rule:** In loops over faces or edges, use `vessel_reconstruction.topology` (indexed `FindKey` access) instead of CadQuery `Faces()`, `Edges()`, `Wires()`, `innerWires()` or `tessellate()`. Time OCP-heavy code with direct timers, not only cProfile.
- **Why:** Ending a Python iteration over an OCP map or array raises `StopIteration` through every OCP exception translator: about 6 ms per call (80 ms the first time), whatever the size.
- **Recurrence (2026-11-11, lane S):** `rhino_exports.export_3dm` called `face.Wires()` for each of the 19,172 Gunnerus app-hull faces: 256 s of a 377 s hull build (now 10 s). cProfile showed only about 100 s of that build. When fixing this pattern, `rg '\.(Faces|Wires|Edges|innerWires|tessellate)\(\)'` over every exporter, not only the module in hand.

### Read ink for a whole fan at once in stroke tracking (MarinaFrame)
- **Date:** 2026-11-11
- **Trigger:** `investigation._track` read ink one sample at a time (`sum(_ink_at(...) for r in radii)` per angle): 49 M calls and 100 M `round()` calls, 300-480 s of the Gunnerus `build_draft`.
- **Rule:** In per-step search loops over angles and radii, compute all sample points in one array and read the mask once (`_ink_hits`). Keep the result bit-identical: take trig values from the same `math` functions, keep elementwise multiply/add (no reductions that reorder sums), round with `np.rint` (half to even, like `round`), and keep the choice loop in its original order. Check identity on a real drawing (byte compare of the enumerated strokes).
- **Why:** The panel enumeration fell from 524 s to 139 s with byte-identical output.

### Test a new spec field through validate_spec (MarinaFrame)
- **Date:** 2026-11-11
- **Trigger:** 7ec97d7 made the intake write `design_draft_m` and `design_draft_source`, but `schema.validate_spec` did not list them. Every sheet-only run whose title-block draft was read (series60-3v-L0) blocked with `input:unexpected_field` before the first model request; unit tests of the writer passed.
- **Rule:** When code adds a field to a spec, add it to `validate_spec` with a value check in the same commit, and test the written spec through `validate_spec`, not only the writer's output.
- **Why:** The writer and the validator are separate modules; only a write-then-validate test sees the mismatch.

### Read a hull score per height sample before chasing shape (MarinaFrame)
- **Date:** 2026-11-11
- **Trigger:** dtmb5415-3v-L0 scored 5.07 % RMS, but every station was 0.3-2.1 % except one 0.05 m height sample at the deck edge: a top 0.004-0.04 m (under 1 px) on the wrong side of a truth sample costs a full half-breadth there, about 6.5 % of half-beam at that station.
- **Rule:** Before changing shape code, print each station's error at its worst sample and its truth/reconstruction top and bottom heights (`benchmarks/hull_accuracy/replay_readings.py` gives per-station rows). Treat single-sample deck or keel misses as a height-measurement problem (which line gives the height), not a section-shape problem. Replay every stored reading before committing a height rule: snapping tops to the profile deck line helped dtmb (5.07 -> 3.10 %) but broke shipd-1-09867 (0.87 -> 8.54 %): its deck line read low under a flat deck at the grid top, where a high top costs nothing and a low one costs a sample at every station (reverted, 5b8a9d5).
- **Why:** The frozen scorer samples heights on a fixed grid; sub-pixel datum errors become large station errors, and the cost is asymmetric at the grid top.

### Never drop a traced station from a rank order (MarinaFrame)
- **Date:** 2026-11-11
- **Trigger:** The polyline reader dropped crowded stations whose bottoms ran into an outer station's bottom, and counted a short transom outline as a station. On CALEB JONES every inner name shifted (identity errors at stations 4-9; 10 wrong of 16 point cells).
- **Rule:** When names come from nesting rank, a drawn line with its own side keeps its rank even when a part of it (the bottom) is lost; keep the part that is its own and flag it. Remove only lines that are not stations (short outlines) before ranking. Read the per-trace log on the worst sheet before changing thresholds.
- **Why:** One missing or extra member of a rank order shifts every name inside it; partial evidence for a station is better than none.

### A value measured on a drawing needs its place rule, a cross-check and its own status when replaced (MarinaFrame)
- **Date:** 2026-11-12
- **Trigger:** GA frame-scale measurement (lane U). The first depth was base line to the poop deck (the model pointed "the deck" near the stern); the next was to the rail or the deck at centreline, 0.7 m above the cargo-tank tops. Lane W found both by comparing the depth with the tops of the read spaces. The first fix replaced the depth with the median space top but kept the status `measured_from_scale`; the PM corrected this.
- **Rule:** When a model points a place that code turns into a dimension: (1) state where the place must lie and check it in code (moulded depth: at side, at mid-length); (2) cross-check the value against an independent reading of the same drawing and flag a disagreement; (3) a value that takes the place of a failed measurement gets a distinct status (`derived_from_space_tops`), keeps the measured value and the reason in its record, and is never checked against the data it came from. Also repeat a small-print reading before relying on it: the same ship gave a frame scale in one request and none in the next.
- **Why:** A dimension that is "measured" in name and substituted in fact makes a downstream check circular, and a pointed line without a place rule is the wrong line on some ships.

### Image coordinates in a model request come from the image actually sent; long lists go in short requests (MarinaFrame)
- **Date:** 2026-11-12
- **Trigger:** GA extents regressed between development rounds (lane W). The request gave label places in the planned image size, but the byte limit shrank the images afterwards, so places were 11 % off; the model wrote "label positions do not match the drawing" and boxed fewer spaces. It also boxed 20 of 71 spaces asked in one request (43 of 43 when asked 43).
- **Rule:** Compute every pixel value that a request states (places, boxes) after encoding, from the sizes of the images written, and test it with a forced shrink. Read the model's free-text note of each reply: it named both causes. Ask a model for at most about 20 items per request, most useful first. Compare each development round per ship with the last good round before calling it better.
- **Why:** A coordinate frame that is off by a resize looks like model weakness, and a long list silently returns a partial answer.

### Keep truth and benchmark inputs out of temporary folders; never clean temp folders by age (MarinaFrame)
- **Date:** 2026-11-11
- **Trigger:** To free disk space, the PM deleted every session-scratchpad folder unchanged for 3 hours. One of them (`scratchpad/wv-agent/`) held the only copies of the C.A. Thayer and Balclutha development truth files, which lane N still needed; other truth files lived under `/private/tmp/claude-501/<boat>/`. They had to be re-transcribed.
- **Rule:** Store every truth file, calibration and benchmark input in the git-ignored `work/` tree (truth: `work/dev-truth/<boat>/`, holdouts: `work/holdout/<boat>/`) with a SHA256SUMS file, never in a scratchpad or `/tmp`. When freeing space, delete only build output (`target/`) and folders you made yourself and know are unused; never delete by age in shared temporary folders while lanes run.
- **Why:** Temporary folders look disposable, and an age rule cannot tell a lane's long-lived input from leftover work.

### The gdrive-mc remote needs the shared-drive flag
- **Date:** 2026-11-12
- **Trigger:** An archive upload to `gdrive-mc:MarinaFrame Data/...` without a flag went to the personal My Drive, and a re-check of verified uploads showed every file as missing.
- **Rule:** For MarinaFrame Data, always pass `--drive-team-drive 0AIHWIsMcKqIRUk9PVA` to every rclone call on `gdrive-mc` (copy, check, lsf, purge). Before you upload, confirm with `rclone lsf` that the destination folder exists on the shared drive. Archive to Drive only data that we still need; scratch runs of merged lanes do not go to Drive.
- **Why:** The remote config has an empty `team_drive`, so without the flag rclone uses My Drive. The user wants Drive kept organized and small.

### Check untracked files before you remove a worktree
- **Date:** 2026-11-12
- **Trigger:** A disk cleanup removed "merged and clean" worktrees with `git worktree remove --force`. The clean check used `--untracked-files=no`, so an uncommitted Sol design file (docs/plans/2026-11-12-linux-sandbox.md) was deleted.
- **Rule:** A worktree is removable only when `git status --porcelain --untracked-files=normal` is empty (ignored files such as target/ and work/ may go). Tell lanes to commit design files when they write them.
- **Why:** `--force` deletes untracked files, and "HEAD is merged" says nothing about files that were never committed.

### Keep read-only reviews inside the permitted worktree boundary
- **Date:** 2026-11-13
- **Trigger:** The thin-ship lane was told not to create another worktree, but a read-only reviewer was launched with tool-level worktree isolation.
- **Rule:** A no-extra-worktree instruction applies to agent tool options as well as shell commands. Omit worktree isolation for read-only reviews; pass exact commit SHAs so the reviewer can inspect the intended range without switching or editing worktrees.
- **Why:** Tool defaults and general isolation guidance do not override a lane-specific workspace boundary.
- **Recurrence (2026-11-14, CFD):** A read-only helper again received the isolation option despite the explicit ban. It was stopped immediately. Check the actual tool arguments against lane boundaries before dispatch, not just the prompt text.

### Identify artificial waterplane caps by their actual surface
- **Date:** 2026-11-14
- **Trigger:** A clipped STEP diagnostic counted the waterplane cap as wetted skin because a trimmed spline bounding box extended beyond its actual geometry.
- **Rule:** Classify a horizontal closure by its planar surface, normal and position, not by underlying spline bbox extrema. Retain real submerged end closures even when slightly curved or tilted. Test cap exclusion and tilted-end retention with exact synthetic solids before using diagnostic areas.
- **Why:** CAD bounding boxes and exact-axis tests are not reliable source-face identities; they can add artificial area or hide a real immersed transom.

### Route audit policy before documentation in CI filters
- **Date:** 2026-11-12
- **Trigger:** The broad `docs/*` CI skip also skipped `docs/dependency-scope-exclusions.json`, which controls the dependency audit.
- **Rule:** Classify executable configuration by its consumers, not its folder. Route audit policy as shared configuration before documentation skips, and keep a regression test.
- **Why:** A documentation directory can contain policy that changes a required security check.
