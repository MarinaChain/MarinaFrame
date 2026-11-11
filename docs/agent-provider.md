# Bounded DeepSeek decisions in MarinaFrame

> **Historical (0.5):** the Python Harness, `vessel-reconstruct agent ...`, `agent_review` and `agent_provider` described here were removed. Rust (`rust-control/`) is the control plane; see `docs/RUST_CONTROL_PLANE.md`. Results below stay as recorded.

## What has actually been verified

On 2026-11-06, two live requests to OpenCode Go returned HTTP 200 and the requested
`deepseek-v4.1-flash` model identity. The text probe returned the correct arithmetic
result. The image probe received actual PNG pixels, read `PORT`, and counted three
red circles correctly. Both responses reported `billing_source: go` and an actual
cash cost of zero. These are capability checks, not a ship-reconstruction accuracy
benchmark. Their complete sanitized receipts are in
[`live_capability_smoke.json`](../artifacts/agentic/provider/live_capability_smoke.json).

The image fixture is independently inspectable at
[`synthetic_probe.png`](../artifacts/agentic/provider/synthetic_probe.png). It was
created for this check and contains no customer material. The private expected
answer was compared after inference; the prompt did not contain that answer.

| Probe | Prompt tokens | Output tokens | Generation latency | Observed cash cost |
| --- | ---: | ---: | ---: | ---: |
| Text | 310 | 44 | 7.69 seconds | $0 |
| Image | 586 | 36 | 7.83 seconds | $0 |

The smoke budget was two generation attempts. Separate controller experiments
record their own finite budgets and carry prior generation reservations forward.
A mock test, cached replay, public model listing, or budget/usage GET is never
counted as a live model decision or as reconstruction quality evidence.

## Provider and data boundary

The current [Go documentation](https://opencode.ai/v2/docs/console/go/) specifies
`https://opencode.ai/inference/go/openai/v1/chat/completions` and model
`deepseek-v4.1-flash`. It requires a client-specific User-Agent and stable
`x-opencode-session`. DeepSeek requires the workspace's Global region setting;
this experiment did not change that setting. The published privacy agreement
states no training and zero retention through November 30, 2026. Recheck these
terms before a later deployment.

The [public catalog](https://opencode.ai/inference/go/v1/models) advertised image
input, tools, structured output, a 1,000,000-token context, and 384,000-token maximum
output. Those are vendor limits, not MarinaFrame's request limits. The exact
retrieved entry is preserved in
[`public_catalog_preflight.json`](../artifacts/agentic/provider/public_catalog_preflight.json).
The upstream [vision format](https://api-docs.deepseek.com/guides/vision/) uses
OpenAI-compatible `image_url` blocks. MarinaFrame sends bounded inline pixels,
not external image URLs that cause the provider to retrieve additional resources.

The adapter accepts controller-built observations, allowlisted tool definitions,
and images with an artifact ID, digest, MIME type, and optional base64 pixels. It
does not search the filesystem, discover credential files, accept model-supplied
paths, execute code, or execute any tool. The controller remains responsible for
source-manifest authorization, semantic approvals, full domain argument validation,
resource limits, and deterministic engineering checks. Source text and images are
explicitly treated as untrusted evidence in the model prompt.

## Access, allowance, and cash accounting

Credentials must be supplied through `OPENCODE_API_KEY` or an explicitly supplied
in-memory key. The adapter has no credential-file CLI option and no alternate-key
fallback. Credentials are never printed or persisted.

The official client source documents the
[account-budget and Go usage reads](https://github.com/anomalyco/opencode/blob/0fdff425ff2ba3e7874321b43709d1e62f539337/packages/core/src/usage-limits.ts).
Budget-read authorization and inference authorization are separate checks. A
budget-read denial does not by itself establish inference access or permission.
The selected admission mode must satisfy its own authorization and accounting
requirements before generation. No account setting, subscription, or spending
policy is changed by the adapter.

There are two explicit admission modes:

| Mode | Required evidence | What it establishes |
| --- | --- | --- |
| `account_zero_budget` (default) | Authenticated applicable $0 all-spend budget and available Go allowance | A provider-enforced account cash guard, under the documented budget behavior |
| `fresh_observed_included_allowance` | Explicit existing-allowance authorization, fresh authenticated usage before every generation, conservative reservation and headroom | Admission from observed included usage; **not** a provider-enforced zero-dollar cap |

OpenCode's [budget rules](https://opencode.ai/v2/docs/console/budgets/) exempt
included Go usage and count paid overflow. The default mode therefore refuses to
generate when it cannot verify the applicable $0 budget. It never automatically
switches to the second mode after a denial.

The second mode was explicitly selected for this bounded pilot. It subtracts one
percentage point from meter headroom for rounding, uses the lowest published
DeepSeek plan-equivalent allowance, and reserves an entire context at peak prices
plus the requested maximum output. Its required headroom is four times all
reserved attempts, including the explicit `prior_generation_reservations` count
carried into a later experiment. Reservations are admission estimates, not cash
charges. All requests are sequential and every failure consumes its reservation.

There remains a race if another client consumes the account allowance between a
usage snapshot and generation. This mode exposes that limitation in its receipts;
it does not imply that Extra Usage is disabled. A returned credit billing source,
positive cost, absent billing confirmation, unknown allowance, denial, timeout,
or insufficient headroom stops the instance. No fallback model, automatic retry,
new subscription, credit purchase, or privacy-setting change occurs.

The [inference usage specification](https://opencode.ai/v2/docs/console/api/inference/)
distinguishes actual `usage.cost`, model `list_cost`, and Go `allowance`. MarinaFrame
preserves that distinction. Unknown actual cost stays `null`; it is never replaced
with a price-based estimate or an invented zero.

## Decision and replay contract

```python
result = provider.decide(observation, tools, images)
# result == {"decision": {"tool": str, "arguments": dict, "reason": str},
#            "receipt": {...}}
```

Tool schemas use `{name, description, parameters}` with an object JSON Schema.
`input_schema` is accepted as a normalized alias. The model receives these schemas
as context and returns a single JSON domain action. The adapter rejects extra keys,
unlisted operations, multiple choices, native multi-tool output, non-JSON text,
duplicate JSON keys, nonfinite values, oversized trees, and truncated completions.
The registry subsequently checks the action's domain semantics and arguments.

Fresh-allowance pilot requests are limited to eight attempts per instance, 24 KiB
of observation plus tools, two images at most, 128 KiB per image, and at most
1,048,576 pixels per image. The pilot used 1,024 output tokens per call; the adapter
also enforces a total output-token reservation, response-byte cap, request-byte
cap, per-request timeout, session timeout, and cancellation.

Cancellation stops the local wait promptly. A request already dispatched may
still complete remotely. The adapter closes after an uncertain transport outcome,
retains the reservation, and will not dispatch another call from that instance.
It does not claim that cancelling a Python wait cancels provider-side inference.

Receipts include the exact requested and returned model identity, input mode,
observation/request/response hashes, prompt hash, artifact digests, request number,
provider completion ID when exposed, latency, and observed usage. They omit keys,
authorization headers, raw image base64, and hidden reasoning. Errors contain
sanitized categories, never raw remote error bodies.

`ReplayAgentProvider` consumes recorded decisions only when the observation,
normalized tool schemas, protocol version, image identities, and pixel-presence
flags match. Changed evidence is a replay mismatch. Replay is labeled `replay`,
preserves whether its origin was live or mock, and cannot be counted as another
live call. Injected test transports are always labeled `mock_transport`.

## Validation and reproducibility

Run:

```sh
python -m pytest tests/test_agent_provider.py -q
```

The boundary suite covers correct parsing, key absence, data authorization,
permission and rate-limit errors, no retry after failure, budget/headroom refusal,
timeouts and cancellation, request/token/image limits, malformed and truncated
responses, model identity mismatch, unknown/positive cash cost, exact replay
matching, and separation of mock/live/replay evidence. These tests validate the
adapter contract; they do not measure model interpretation accuracy.

For an exact offline replay of a completed controller trace, use
`export_replay_transcript(store.events, tool_schemas, image_loader=...)` followed
by `verify_replay_transcript(transcript)`. The application supplies a trusted,
bounded artifact loader keyed by the recorded artifact ID. Export checks the
controller event chain, the stored observation-only digest, and the provider's
broader context digest independently; those two digests cover different objects.
It embeds the verified image bytes needed to replay the same inputs. Verification
reports zero new generation requests and zero CAD operations. It does not imply
that a newly executed CAD job would reproduce nondeterministic artifact bytes.

For a live controller run, configure `OPENCODE_API_KEY` outside version control,
explicitly authorize the selected source manifest, and select the desired
admission mode. Never copy credential files into the repository.
The snapshot and source index are in
[`provider_research.json`](../artifacts/agentic/provider/provider_research.json).
