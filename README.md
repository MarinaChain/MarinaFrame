# MarinaFrame 0.4

MarinaFrame is a **domain harness for reconstructing provisional 3D hull envelopes from calibrated 2D section drawings**. A deterministic policy or the provisioned DeepSeek model can inspect source pixels, choose retained contour alternatives, request CAD construction, inspect renders from the exported STEP, revise a selection and request validation. Rust owns the task lifecycle and trust boundaries; Python, CadQuery and OpenCascade remain the geometry and image-processing workers.

The supported input is specific. A person supplies section panels, longitudinal station positions, scale, datum, elevation intervals, symmetry and closure assumptions. MarinaFrame measures the curves and constructs the corresponding envelope. It does not infer a complete vessel from an arbitrary collection of shipyard drawings. Blender is not required, and model-generated code is never executed.

**Every candidate has `engineering_approved=false`.** Passing checks means the recorded numerical, provenance and CAD conditions passed for the selected source evidence. It does not establish that the selected line is the intended hull, or that the result is suitable for fabrication or navigation.

## What changed from published 0.3

- Failed geometric validation stays failed on a cache hit, after restart and through finalization. The contract binds source, selection, generation, revision, STEP, validator identity, measurements and evidence. Independent Python and Rust reviews cover stale, malformed, contradictory and altered records.
- The Rust executable owns durable intent, events, checkpoints, typed decisions, provider receipts, cancellation, native admission and final review readiness. Its Python bridge calls `DomainTools`, never the old Python `Harness`.
- Actual live requests carry exported-STEP image pixels and their hashes. Evidence separates retention, revision, refusal, failed schema responses and uncertain outcomes. Final live candidates require recorded current body and oblique images plus current passing validation.
- Source processing retains connected-endpoint interpretations and measured narrow features. The old centroid remains inspectable. Particular development cases improve; an underresolved tangency and raw terminal spurs remain documented failures at unchanged gates.
- A local Rust review interface supports bound interventions, regeneration, stale-tab refusal, cancellation and resume. Old images remain visibly older evidence.
- The data pipeline includes additional archival acquisition, separate rights scopes, full annotation-schema validation, grouped datasets and an actual small local training experiment. The trained pixel classifier is experimental and **not enabled in the reconstruction policy**. DeepSeek weights were not fine-tuned.

Read [the full 0.4 report](docs/V04_REPORT.md), [independent evaluation](docs/INDEPENDENT_EVALUATION_V04.md), [source fidelity](docs/SOURCE_FIDELITY_V04.md), [data and learning](docs/DATA_LEARNING_V04.md), and [reliability](docs/INDEPENDENT_RELIABILITY_V04.md). Historical 0.3 results remain in [AGENT_RESULTS.md](docs/AGENT_RESULTS.md); they are not relabelled as new results.

## Supported installation

The exercised platform is **Linux x86_64, Python 3.12.14, Rust 1.99.1 and CadQuery 2.7.0**, using committed dependency locks. macOS, Windows and other CPU architectures are untested. Linux process controls are resource and lifecycle boundaries, not a sandbox for hostile code.

From a source checkout, with Python 3.12 and rustup installed:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-linux-py312.lock
python -m pip install --no-build-isolation --no-deps .
rustup toolchain install 1.99.1 --profile minimal
cargo build --release --locked --workspace
```

Optional annotation tools use `requirements-data-linux-py312.lock`; install that hash-locked file when using the data pipeline. Ordinary deterministic reconstruction needs no API key or GPU. The runtime package also contains the built Rust executable and the project's Python wheel; it does not bundle the third-party native environment.

The separate current learning lock uses Pillow 13.0.0. Historical training used 12.3.0; its advisories and unchanged-model compatibility replay are documented in the dependency report. The older, unhashed `requirements-lock.txt` is retained as historical context and is not the supported installation input. Use the hash-locked files named here.

### Run the Rust deterministic path

Use a new task directory for each reconstruction. In the managed environment used for this work, active runs must be outside the synchronized workspace: completed workspace runs have acquired restored transaction debris after publication. The verifier rejects that debris. The tested mitigation is active execution under `/tmp`, then a completed-only copy and verification across another process/tool boundary. The external cause remains unconfirmed.

```bash
MARINAFRAME_RUN_ROOT="$(mktemp -d /tmp/marinaframe-run.XXXXXX)"
MARINAFRAME_CONTROLLER="$(pwd)/target/release/marinaframe"
python examples/make_agent_example.py --out "$MARINAFRAME_RUN_ROOT/input"

"$MARINAFRAME_CONTROLLER" run \
  --task "$MARINAFRAME_RUN_ROOT/task" \
  --source "$MARINAFRAME_RUN_ROOT/input/spec.json" \
  --worker-python "$VIRTUAL_ENV/bin/python" \
  --policy deterministic

"$MARINAFRAME_CONTROLLER" verify --task "$MARINAFRAME_RUN_ROOT/task"
python -m vessel_reconstruction.rust_review export \
  --task "$MARINAFRAME_RUN_ROOT/task" \
  --controller "$MARINAFRAME_CONTROLLER" \
  --out "$MARINAFRAME_RUN_ROOT/review.html"
```

The Rust CLI prints structured JSON. **Inspect `status`; exit 0 does not itself mean a candidate passed.** A valid command can record abstention, block, cancellation or provider failure. CLI/protocol errors return exit 2. `awaiting_human_review` is a provisional handoff, never engineering approval.

### Run the live policy

Configure `OPENCODE_API_KEY` privately in the launching process. Do not put its value in an argument, prompt, source file or report. The fixed integration uses OpenCode Go's OpenAI-compatible endpoint and requires returned identity `deepseek-v4.1-flash`. Native workers receive a scrubbed environment without the provider credential.

```bash
"$MARINAFRAME_CONTROLLER" run \
  --task "$MARINAFRAME_RUN_ROOT/live-task" \
  --source "$MARINAFRAME_RUN_ROOT/input/spec.json" \
  --worker-python "$VIRTUAL_ENV/bin/python" \
  --policy live \
  --provider-transfer-basis 'Project-generated drawing; authorized for this provider inference.'
```

Only send material whose provider-transfer scope is established. Local training/testing authorization is separate from external inference and redistribution. The November 2026 research campaign has **no aggregate request, token or spend cap**; earlier pilot limits are historical. Per-request limits, bounded retries/backoff, cancellation, disk admission and no-progress controls remain. Receipts distinguish completed, failed, not-sent and unknown outcomes; missing cost is not zero.

The default outer worker limit is 210 seconds wall time, 180 seconds CPU and 5 GiB address space. Retained native workers also enforce their own 180-second wall, 120-second CPU and 4 GiB limits. Provider calls use a 90-second timeout and 2,048 output tokens. At most four bounded images and 96 KB of structured observations enter a request. These are operating bounds, not accuracy guarantees.

### Resume and recover

```bash
"$MARINAFRAME_CONTROLLER" status --task "$MARINAFRAME_RUN_ROOT/task"
"$MARINAFRAME_CONTROLLER" cancel --task "$MARINAFRAME_RUN_ROOT/task"
"$MARINAFRAME_CONTROLLER" resume --task "$MARINAFRAME_RUN_ROOT/task" --clear-cancel true
```

`--steps N` pauses after an explicit number of decisions. A lost or exact earlier checkpoint can be recovered from committed events with `recover-checkpoint`; arbitrary corruption and unfinished worker evidence are not adopted. Unknown provider requests are never automatically repeated. `resume --continue-after-unknown true` records an explicit acknowledgement and can start a new decision while retaining the old uncertainty.

Mutation requires the captured controller and worker identity. Preserve the matching runtime to continue an existing task. Start a new task after an upgrade instead of editing identity fields. Development records written before the floating-point round-trip fix can fail current exact audit checks even when their bytes are unchanged; the compatibility report preserves and explains those records.

## Review and interventions

The [Rust review guide](docs/RUST_REVIEW.md) documents the actual tested browser workflow. To open a local deterministic operator session:

```bash
python -m vessel_reconstruction.rust_review serve \
  --task "$MARINAFRAME_RUN_ROOT/task" \
  --controller "$MARINAFRAME_CONTROLLER" \
  --port 8767 --allow-actions --actor human_operator
```

Open the one-time loopback link printed by the server. Typed interventions include task, event head, generation and revision. Rust checks all four under its task lock; stale tabs cannot silently edit a newer candidate. Contour changes invalidate dependent readiness and require a new build, renders and validation. Live-provider tasks are read-only in the browser; continuation uses the CLI's explicit source-transfer configuration.

An actor label records who the caller says performed an action; it does not authenticate a professional. No qualified naval architect participated in these experiments. The review packet retains assumptions, unresolved lines, calibration questions and failed checks for a qualified reviewer.

## Geometry and evidence

| Question | Evidence and limit |
| --- | --- |
| Was the intended source line selected? | Retained alternatives, source pixels and semantic review; a CAD pass cannot answer this. |
| Does CAD reproduce the selected trace? | Reimported STEP sections against selected-source samples; default maximum distance 1.1 mm. This is distinct from independent vessel truth. |
| Is the shape independently accurate? | Sealed reference comparisons where suitable truth exists, with all attempted cases in the denominator. Authentic whole-hull truth remains unavailable. |
| Is the export internally valid? | Solid, shell, closure, finiteness, units, dimensions, volume and immutable-artifact checks. Valid topology alone is insufficient. |

Input/JSON geometry uses **metres**. OpenCascade, STEP and STL coordinates use **millimetres**; STL has no inherent unit declaration. Longitudinal `x` is supplied, starboard half-breadth `y` is measured, and elevation `z` is positive upward. Port geometry uses the recorded symmetry assumption.

The result is an enclosed, interpolated hull envelope over supplied stations and height domains. Terminal, upper and nonzero-width lower closures are mathematical assumptions. Envelope volume is not certified displacement. Thickness, structure, compartments, equipment, stability, current vessel condition and fabrication readiness are outside the demonstrated scope.

## Python command line

The legacy Python controller (`agent_harness`, `agent_cli`, `agent_review`, `agent_provider`), the local workbench server, its job queue and the Python review log were removed in 0.5. Rust is the only control plane. `vessel-reconstruct` keeps two commands that use only the pipeline: `reconstruct SPEC --out DIR` (isolated deterministic engine run) and `verify RUN`.

The 0.4 control-plane comparison used default policies with different view schedules, so raw product-arm latency is not a language-only comparison. The performance study aligns source selections, CAD operations and view counts explicitly. Native CAD remains the geometry implementation; no general Rust CAD speedup is claimed.

## Verification and dependencies

```bash
python -m pytest -q
cargo test --locked --workspace
cargo clippy --locked --bin marinaframe -- -D warnings
python scripts/smoke_rust_installed.py \
  --controller target/release/marinaframe --out /tmp/marinaframe-installed-check
```

The installed smoke requires a non-editable wheel/package installation. It generates its input, runs actual native construction, reimports STEP, validates and verifies evidence without `PYTHONPATH` or a provider key. Unit, protocol, controlled-fault, installed, browser and live-evaluation outcomes are reported separately.

See [Python verification](docs/PYTHON_VERIFICATION_V04.md), [independent Rust review](docs/INDEPENDENT_RUST_REVIEW.md) and [dependency/license evidence](docs/DEPENDENCIES_V04.md). The locked Rust audit includes patched Tokio. Three VTK 9.3.1 advisories remain documented under the supported-source routing scope; the installation is not universally vulnerability-free. Native/OS security and every redistribution obligation have not been comprehensively certified.

CI configuration now builds/tests Rust and exercises the installed Rust/Python path. New changes were tested locally and **have not been pushed**, so no new remote CI result is claimed. The verified published 0.3 draft PR #2 remains unmerged; its successful CI belongs to its exact historical head.

## Source, data and publication

This continuation starts from published 0.3 head `5b0b48e3dd9bcef25427d27ce800118935f58d1a`, draft PR #2. Application freeze, documentation revision and release archive identities are recorded separately. No PR was merged, no new work was pushed, and no application was deployed.

The repository's all-rights-reserved license and visibility remain unchanged. Dataset and dependency rights are separate. Restricted originals and derivatives are excluded from unrestricted release archives; manifests record acquisition attempts, hashes, permitted local uses and unresolved transfer/distribution scope. Historical paths into omitted datasets require the exact separately supplied evidence to replay.

The research evidence includes failures and small procedural cohorts. Clean/scanned pairs, pages and augmentations are not independent vessels. A local event hash chain proves consistency relative to recorded bytes; it is not a digital signature, authenticated identity or professional certification.
