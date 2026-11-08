# MarinaFrame lessons

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

### Repartitioned holdouts are hull-disjoint, not family-disjoint
- **Date:** 2026-11-08
- **Trigger:** All original Ship-D clusters were already represented; a new seed cannot establish independence from those broad families.
- **Rule:** Name the approved replacement split “hull-disjoint (v2)” in manifests, README and scorer output. State that clusters can share broad families with frozen splits. Exclude every new cluster containing any previously rendered hull. Keep the truth sealed; run no reader or scorer during generation or development. Score only at frozen checkpoints.
- **Why:** New partition labels do not prove new hull families.

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
