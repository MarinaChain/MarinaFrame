# Measured ship CAD language (W13)

Status: development draft. This is not a complete-vessel reconstruction system or an engineering approval path. All outputs have `engineering_approved=false`. Only the Rust controller can decide review readiness. This separate draft executor does not call or replace that decision.

## Design

`ship-cad/v1` is strict JSON, not Python. JSON uses the existing typed provider transport and does not need an expression parser. A program has exactly `schema` and `components`. There are at most 64 components. Each component has exactly `id`, `op`, `source` and `args`. Identifiers contain letters, digits, `_` and `-`, start with a letter, and have at most 64 characters. Duplicate JSON keys, unknown fields and unknown operations are rejected.

Example (references, not dimensions):

```json
{"schema":"ship-cad/v1","components":[
  {"id":"house","op":"deckhouse",
   "source":{"view":"plan","region":"house_plan","method":"closed_outline"},
   "args":{"outline":"house_outline","height":"house_levels"}}
]}
```

| Operation | Required references | Construction |
|---|---|---|
| hull | sections | Existing multi-region hull pipeline |
| deck | outline, height | Plan polygon between measured lower/upper levels |
| deckhouse | outline, height | Plan polygon between measured profile levels |
| bulwark | outline, height, thickness | Polygon wall with inward offset |
| appendage | outline, span | Profile polygon extruded over measured transverse interval |
| opening | outline, height, target | Subtract a plan prism from an earlier component |

An opening cannot erase its complete target. Profile-window openings are not implemented by the plan-prism operation and must remain unresolved. A deck needs two levels; plate thickness is never invented. Bulwark thickness needs a measured length; a measured height interval is not a length.

The model names the component, source view, region and measurement method. It does not provide physical coordinates, sizes or offsets. Only the host drawing adapter supplies the measurement map. Invalid, absent or failed measurements leave an **unbuilt draft guess with a reason**, not a plausible box. Even fully measured solids remain drafts because semantic line identity and drawing calibration need review.

## Tools and provenance

The Rust provider adds a narrow `ship_cad` vision purpose. It returns a typed program, region proposals and measurement requests, with no approval fields. Numeric region coordinates are selectors in **0–1000 whole-attachment coordinates**, not dimensions. The host maps them to drawing coordinates with the recorded view bounds and inverted vertical axis.

`ship_measure.investigate` accepts only `{tool, view, region}`. Host views bind the drawing file, unit scale, origin, layers and regions. Tools are:

- `closed_outline`: select exactly one source polygon; join open edges only at matching endpoints. Reject gaps, branches, disconnected loops and ambiguous closed polygons. Region-box dimensions never become geometry.
- `parallel_lines`: require exactly two horizontal source levels in the region. Return the measured interval and entity identifiers. Multiple levels cause abstention.
- The development hull adapter reuses the existing Gunnerus drawing-only frame/region reader. It preserves section evidence and abstentions. Its semantic station rules are provisional, not model-discovered setup.

Each measurement records source hash, view, region, method, entity identifiers, calibration and value. Each component records these measurements, build outcome, bounding box and volume. STEP uses millimetres; language values and reports use metres. The existing hull builder uses millimetres and is converted explicitly before assembly.

## Safety model

The language cannot name imports, arbitrary functions, files, URLs, output paths, tolerances or gates. Numeric component arguments are rejected in Rust and Python. Measurements are trusted host evidence, not model-supplied records. The primary source is selected by operation, not JSON key order.

The CAD worker uses the existing supervisor for deadlines, process-group cleanup, CPU/file/output limits and an environment without provider credentials. Those limits alone are **not** a sandbox. W13 adds a macOS Seatbelt deny-default profile: no network; task-local writes; read-only access to runtime libraries and this worker source. The root directory itself can be read for dynamic-loader startup, not its descendants. Runtime library reads are necessary and are not drawing/model access. Linux execution fails closed until an equivalent OS profile exists. macOS does not enforce the existing address-space limit; this limitation remains.

Only trusted code interprets operations. This does not protect against a malicious same-user process changing trusted libraries or the kernel. Drawing parsing happens in the development harness, before CAD execution; it is not a sandbox for hostile document parsers.

## Cross-view checks

`step_cuts` independently reimports the exported STEP and cuts profile (constant y), plan (constant z) and body (constant x) planes. `check_views` compares sampled source traces and cut points with symmetric nearest-point distance. Missing, empty, nonfinite or displaced views block. The 50 mm draft diagnostic tolerance is not an engineering gate. A veto always blocks; a positive check never approves.

Host-bound audit input supplies planes, independent traces and source provenance. The Gunnerus arm supplies the lines-plan centreline profile; unresolved plan-waterline and body-station identity remain explicit blocking gaps. The existing W12 Rust finalization veto is unchanged. W13 does not claim that W12 reviewed a draft which never entered that finalization path.

## Usage

Run from the project worktree with its source explicitly selected:

```sh
PY=/Users/jonathanjie/Documents/workspace/MarinaFrame/.venv/bin/python
export PYTHONPATH=$PWD/src
cargo build --locked -p marinaframe-control
source /Users/jonathanjie/Documents/workspace/MarinaFrame/scripts/load_opencode_keys.sh
$PY -m benchmarks.ship_cad.run \
  --sources /Users/jonathanjie/Documents/workspace/MarinaFrame/work/sources/gunnerus \
  --controller "$PWD/target/debug/marinaframe" --out "$PWD/work/w13/new-run"
$PY -m benchmarks.ship_cad.score --run "$PWD/work/w13/new-run" \
  --truth /path/to/cached/hull-truth
```

Do not reuse an existing output directory. Every request and attachment uses the Rust vision request/receipt path with hashes, dimensions, bytes and crop box. Per-request provider and worker limits remain. There is no aggregate call, token or spend cap. Repeated invalid schemas or failure to increase the number of built components stops the run. A successful isolated height measurement alone is not component progress. Frozen controller copies avoid rebuild races. No drawings, rendered sheets, STEP files, BReps or source-derived geometry are committed.

## Results and checks

Evaluation uses caller-reviewed Gunnerus view crops and calibration, not autonomous setup discovery. The model reads vector-rendered GA/profile/body attachments; original PDFs are available but are not inputs to this arm. Final results follow below. Local evidence is under ignored `work/w13/`. All attempts, including rejected schemas and interrupted requests, are included in usage. The available truth STEP is **hull-only**, despite the requested complete-vessel description: one solid, 145 faces, maximum z 6.622 m, volume 1302.280 m³. The GA labels A-deck at 6.687 m and shows upperworks above it. Thus upperworks presence against a complete-vessel truth, bounding-box errors and volume errors cannot be established from this source. They remain not measurable, never zero.

### Model usage and failed attempts

All five drawing arms together used 13 receipted requests and 39 image attachments: 29,546 prompt tokens, 11,876 completion tokens, provider list USD 0.0115575, observed charge USD 0.00. All receipts include usage. Eleven requests completed and two failed the typed schema. The CAD-only retries make no model calls.

The initial arms rejected missing required arguments, a measurement in the wrong view, and a hull source name that did not match the host measurement. One arm was stopped when alternating level measurements extended the original no-progress rule without producing components. The final prompt names the exact host hull source. The final source-selected program resolves the hull but not the upperworks.

Final arm measurement coverage: 70 hull stations read, frames 6 and 16 refused. Main deck: 103 possible closed outlines and 25 levels; deckhouse: 20 outlines and 36 levels; bulwark: 4 outlines, 30 levels and no measured thickness; forepeak store: 5 outlines and 28 levels. A hatch outline was measured, but its 13 competing height levels prevent an opening. Skeg/appendage requests in earlier arms failed outline/span measurement; the final program omitted a separate appendage. These are draft guesses or missing components, not accepted blocks.

The default worker stopped on its CPU limit. A 600-second/480-CPU-second retry then stopped at its 256 MiB aggregate output limit (two STEP exports). A separate bounded retry uses 512 MiB per file and 1.5 GiB aggregate output. No guard or geometry tolerance was weakened.

### Verification

- `make test-quick` before the final view guard: passed. Python 674 passed, 17 CAD tests deselected; Rust tests, formatting, Clippy and secret scan passed.
- `make test-full`: run once; failed in existing `worker_stalled_before_reading_large_request_remains_time_bounded` at the expected `TimedOut` assertion after about 122 seconds. Concurrent native benchmark activity held the shared admission slot. The isolated test then passed (1 test, 77.20 seconds including queue wait). The full tier was not rerun and is not reported as passed.
- Six safety mutations caught. Reproduce with `PYTHONPATH=src $PY scripts/check_ship_cad_mutations.py`.
- Review fixes have regression tests: sorted JSON arguments, asymmetric appendage span, empty opening target, and independent STEP audit integration.
- `refresh-codesight` generated a local index but its bootstrap failed with `ModuleNotFoundError: render_bootstrap`. No generated index is committed.

### Independent exported-hull score

The bounded expanded-output retry wrote a hull STEP. Independent import found valid CAD with 17 solids, volume 1978.766 m³, maximum bounding-box coordinate error **0.964481 m**, and relative volume error **+51.9463%** against the hull truth. These are poor draft scores, not a complete-vessel result. The main deck, deckhouse, bulwark, forepeak store and opening remain unbuilt guesses; their dimensions and volume errors are not measurable. A separate skeg is missing from the final model program.

The initial CPU/output-limited runs have no completed result and are not counted as successful executions merely because partial STEP files exist. Independent scoring of the expanded retry is reported separately from its worker completion/audit state.

The real-CAD Python tier passed separately: **17 passed, 674 deselected**. After that run, a wrong-view regression test was added and passed: a profile outline cannot become a plan deckhouse. The full targeted W13 suite passed **30 tests**. Six safety mutations now pass, including that new wrong-view guard.

The expanded retry completed in **419.95 seconds**, exit 0. It built the hull and left all five other requested components unbuilt. Independent cuts contain 16,135 profile, 16,262 plan and 4,749 body samples. The profile comparison failed with **3.837445 m** maximum symmetric sampled distance. Plan and body comparisons have no independently resolved source identities and remain missing. Thus cross-view status is **blocked**; no readiness or engineering approval is asserted. W12 did not review this separate draft.

Final post-view-guard quick tier: **675 Python tests passed, 17 CAD tests deselected**; all Rust quick tests, format, Clippy and secret scan passed. No second full-tier run was made.

### Existing Gunnerus hull metrics

The exported retry hull was scored with the existing 0.1 mm reconstruction mesh and cached truth sections. Main-band station half-breadth RMS is **0.822427 m** (median station RMS 0.279132 m); between-station RMS is **0.832426 m** over 143 cuts. At 2.5 m draft, section-integrated volume is 481.941275 m³ vs truth 486.336577 m³ (**−0.903757%**), and waterplane area is 278.697560 m² vs 279.377932 m² (**−0.243531%**). These submerged metrics do not excuse the +51.95% whole-envelope volume error or upper profile failure. They reproduce the existing deterministic region pipeline, not a demonstrated LLM geometry improvement.

Remaining work: robust semantic GA perimeter/level selection, measured thickness/span tools, independent plan/body checks, complete-vessel truth, and Rust-controlled draft admission with W12 veto. W13 establishes a guarded draft-program path; it does not deliver a correct whole vessel.
