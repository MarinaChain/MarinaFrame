# Optional measurement proposals

Ordinary reconstruction remains offline and deterministic. `model_proposals.py`
is an optional evidence adapter, not a source of accepted CAD coordinates. Every
proposal has `review_required=true`, `accepted_observation=false` and
`engineering_approved=false`. It is not imported by the reconstruction pipeline.

## Provider verification: 7 November 2026

Primary sources checked:

- [OpenCode Go](https://opencode.ai/v2/docs/console/go/)
- [Live model metadata](https://opencode.ai/inference/go/v1/models)
- [Inference API](https://opencode.ai/v2/docs/console/api/inference/)
- [Budgets](https://opencode.ai/v2/docs/console/budgets/)
- [Harness sessions](https://opencode.ai/v2/docs/console/harnesses/)

The live catalog advertises `deepseek-v4.1-flash` with text and JPEG/PNG/GIF/WebP
input, text output, a 1,000,000-token context and 384,000-token output limit, at
`https://opencode.ai/inference/go/openai/v1/chat/completions`. This is metadata,
not a successful image-inference test. Provider image pixel/tokenization limits
were not established. Our adapter caps each PNG at 262,144 pixels and 128 KiB,
one crop/request, 1,024 output tokens, a 30-second I/O timeout and a 64 KiB
response, with no retries. The I/O timeout is not a strict total request deadline.

The Go page lists $0.15/M input and $0.60/M output off peak, with a 2× peak
multiplier. Its privacy table says no training and zero retention under a
DeepSeek agreement valid through 30 November 2026. These are provider statements,
not an independent privacy audit. Workspace region/training rules still apply.

Go can fall back to paid credits when Extra Usage is enabled (the default for Go
Teams). A key does not establish overflow settings or a cash budget. Here the
supplied second-line key was used only in a read-only catalog GET, which returned
HTTP 200. This public endpoint does **not** prove key/subscription validity.
**Zero generation calls were made.** No drawing or crop was sent for inference.

## Evidence and credentials

Supply `OPENCODE_GO_API_KEY` through an approved process secret mechanism.
`.env.example` is a placeholder. Ordinary CAD workers strip provider credentials.
Never put a key in a specification, command argument, source, prompt or report.

Each crop has a source SHA-256, identifier, page, global pixel rectangle and
declared feet/inches/eighths convention. Responses must reference the same
evidence. Duplicate keys, unexpected fields, nonfinite values, malformed
literals, changed units/coordinates and silent digit repairs are rejected. The
local parser recomputes metres from the raw literal. Printed instructions are
untrusted data; the model receives no tools. Validating format/conversion does
not establish correct transcription.

The adapter requires synthetic-data authorization and an explicit cash ceiling.
It reserves the full advertised context at the recorded peak prices for each
call ($0.3012288 with the current output cap), including failed/timeout attempts.
This conservative client reservation uses a dated price snapshot. Recheck prices
and set provider-side spending controls before later use; it does not change
Console settings or guarantee future prices.

## Frozen comparison

```bash
PYTHONPATH=src python -m benchmarks.proposal_experiment \
  --freeze --dataset artifacts/proposal-cells --out artifacts/proposal-mock.json
```

The 13 generated cells include explicit measurements, faint/blurred text,
invalid inch/eighth fields, missing digit/cell, ditto mark, header and printed
instruction. Images and labels are frozen by SHA-256. Version 2 uses opaque
crop-hash identifiers and filenames: evaluator-only class names never enter live
requests. A review found descriptive identifiers in the original mock-only
experiment; that evidence is retained, and the issue was fixed before any live
call. Tesseract processes the
same crops. A scripted mock deliberately suggests one wrong literal to exercise
selective-error scoring. **Mock scores do not measure a VLM.** Label bytes are captured and hash-checked before inference, then decoded for
scoring only after responses; target values do not enter live requests.

Observed here: Tesseract emitted 6/13, all six exact, with seven abstentions. The
mock emitted six, one intentionally wrong. Exact OCR/mock agreement retained
five proposals with eight abstentions. This is a development diagnostic, not
an unseen accuracy result. No geometry used these proposals. Human correction
time, nondeterminism and live model quality remain unmeasured.

After separately authorizing provider, the exact synthetic dataset and budget,
the same frozen inputs can use:

```bash
PYTHONPATH=src python -m benchmarks.proposal_experiment \
  --dataset artifacts/proposal-cells --out artifacts/proposal-live.json \
  --provider live \
  --authorize-dataset-sha256 EXACT_MANIFEST_SHA256 \
  --authorize-cash-usd APPROVED_AMOUNT
```

Use the SHA-256 of that dataset's `manifest.json`, not a descriptive name. No
default budget permits network generation. Every source crop is captured through
bounded, no-follow directory access and checked against the manifest before the
first possible API call; labels are not inference inputs. The adapter needs a
per-call reservation for every requested call and serializes transport with budget
reservation. It records prompt/request/response hashes, latency and bounded
numeric usage. A failure checkpoints the attempted call, stops further calls and
records remaining cases as abstentions. Reports distinguish actual transport
attempts from validated responses and never infer success from `--provider live`.
Live results remain unavailable because spending/overflow authorization and
provider-side policy were not established.
