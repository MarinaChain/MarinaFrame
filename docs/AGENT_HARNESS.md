# MarinaFrame 0.3: a model inside a bounded CAD workflow

> **Historical (0.5):** the Python Harness, `vessel-reconstruct agent ...`, `agent_review` and `agent_provider` described here were removed. Rust (`rust-control/`) is the control plane; see `docs/RUST_CONTROL_PLANE.md`. Results below stay as recorded.

## Scope

The harness coordinates a pretrained decision model and a deterministic reconstruction engine. It accepts **calibrated section drawings**, with declared panels, longitudinal stations, units, symmetry, datum, scale and vertical extents. It does not infer those facts from an arbitrary drawing set. Its output is a provisional hull envelope, not a fabrication model, approved ship design or certified displacement calculation.

The old `reconstruct` command remains the deterministic 0.2 engine path. New contour inspection and selection live behind domain tools; the strict original contour ambiguity checks remain in that engine. No arbitrary Python, shell, CAD script, model-supplied path, external network tool, plugin installation or acceptance-threshold change is exposed to the model.

## Components and authority

| Component | Implementation | Responsibility |
| --- | --- | --- |
| Task and evidence | `agent_harness.TaskStore` | Exclusive controller lock; hash-chained events; immutable event history; cached state; source/domain checkpoint binding |
| Execution controller | `agent_harness.Harness` | Budgets, cancellation, deadlines, typed action envelope, no-progress/rejection limits, recovery/termination, operator accounting |
| Policy boundary | `agent_provider.OpenCodeGoAgentProvider` | Exact provider/model, explicit external-data authorization, bounded images/JSON, included-use admission, sanitized receipts, no automatic retry |
| Offline policies | `DeterministicPolicy`, `ScriptedPolicy`, `ReplayAgentProvider` | Source-grammar comparison, mock protocol tests, exact frozen decision replay respectively |
| Domain tools | `agent_tools.DomainTools` | Captured inputs, source-bound candidate IDs, reversible selections, preserved alternatives, isolated CAD builds |
| Visual/geometry worker | `agent_render_worker` | Bounded source inspection; actual exported STEP reimport; named opaque views; source-to-STEP section checks |
| Review | `agent_review`, `agent_cli` | Offline visual evidence/trajectory interface; exported operator decision; explicit selection/regeneration; no engineering approval |

The policy proposes one action. The controller checks it. The domain executor checks the arguments and evidence again. The engine owns geometry invariants and publication. Model text cannot waive a failed check. Source annotations and images are untrusted evidence, not instructions.

## Actual tool contract

Every action is exactly `{ "tool": "name", "arguments": {}, "reason": "short explanation" }`. Extra envelope keys, unknown tools, nonfinite/deep/oversized JSON and unsupported arguments are rejected. Provider outputs must be one completed JSON response; native parallel tool calls are not accepted.

| Tool | Accepted arguments | Effect and limits |
| --- | --- | --- |
| `inspect_source` | Optional known `section_ids` | Inspect bounded batches of frozen source pixels. Return candidate IDs, support diagnostics, grid evidence, preserved alternatives and hashed images. No new calibration is invented. |
| `select_contours` | `selections: [{section_id, candidate_id}]` | Only already inspected source-bound selectable candidates. Creates a provisional revision, retains excluded strokes, invalidates prior current-generation validation. |
| `build_provisional` | Empty object | Runs the unchanged engine with selected pixel corridors, inside the existing bounded native worker. Failed attempts retain the last valid candidate. |
| `render_candidate` | `view`: body, plan, profile or oblique | Verifies and reimports an exported STEP. A preserved older candidate is explicitly marked stale and cannot pass final validation as the current revision. |
| `validate_candidate` | Empty object | Verifies immutable run evidence and actual STEP geometry/section cuts. Reports geometry consistency and remaining review obligations. |
| `finish` | `outcome`: candidate_ready_for_review or abstain; `summary` | Controller termination. A proposed successful finish runs deterministic validation again. It cannot grant engineering approval. |

There is deliberately no arbitrary-coordinate editing tool. Coordinates, declared units, topology, extents and scales remain source-bound engine inputs. Unsupported symmetry, nonmonotone sections, missing units/calibration and speculative station correspondence are not repaired by model invention.

### Source grammar

Inspection may propose both broad-contrast and high-contrast continuations. Darkness only generates a hypothesis. A strict repeated orthogonal lattice can explain grid strokes; automatic selection requires a uniquely supported remaining contour. A faint unexplained component prevents this automatic inference. The selected contour remains **semantically provisional**, even when grid grammar proposes one candidate. The UI preserves the alternatives for review.

The development iteration also fixed a real corridor-compiler defect: fractional calibration endpoints can lie within rounded raster-row bounds. Corridors now span the actual retained trace rows; the engine's original coverage check was not relaxed. Source-to-CAD fitting remains adaptive and uses the earlier absolute geometric tolerance.

## Run offline

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-linux-py312.lock
python -m pip install --no-build-isolation --no-deps -e .
python examples/make_agent_example.py --out data/examples/agent
vessel-reconstruct agent run data/examples/agent/spec.json \
  --out /tmp/marinaframe-task --policy deterministic
vessel-reconstruct agent verify /tmp/marinaframe-task
vessel-reconstruct agent review /tmp/marinaframe-task --out agent-review.html
```

Exit 0 from `agent run` means `awaiting_human_review`, not approved geometry. Exit 2 reports the actual blocked, failed, cancelled or exhausted outcome. `agent status TASK` shows counters, policy and source-manifest hash. `agent verify TASK` checks the event chain, state cache, frozen source inputs, domain checkpoint, observed artifact hashes and valid candidate-run manifests. Hashes are local integrity evidence, not external signatures.

Use `--ambiguous` when generating the example to add a faint competing contour. The fixed source-grammar policy should abstain. This is a useful review demonstration, not an archival vessel or independent accuracy test.

## Actual review and correction

Open the offline review HTML. It embeds the source overlays, preserved alternatives, named STEP renders, section comparisons, task state and decision history without external requests. Select candidates and click **Download selection decision**. Then:

```bash
vessel-reconstruct agent step /tmp/marinaframe-task \
  --decision selection-decision.json --actor human_operator \
  --note "Describe the source evidence supporting these choices"
vessel-reconstruct agent resume /tmp/marinaframe-task --policy deterministic
vessel-reconstruct agent review /tmp/marinaframe-task --out revised-review.html
```

The role is recorded, not independently authenticated. Automated QA used `assistant_operator`, not `human_operator`; it is neither a naval architect's decision nor expert gold truth. Each operator action consumes the same task action/build budgets and remains separate from model inference. The UI cannot execute a tool or approve engineering by itself.

## Live provider

See `agent-provider.md` for exact endpoint/model/capability evidence and privacy/billing qualifications. Put an authorized credential in `OPENCODE_API_KEY` through your approved secret provisioning; do not place it in command arguments, a repository, HTML, or a transcript.

Live processing requires the **exact captured source-manifest hash**. To capture a task without a provider transfer, run live mode without an authorization hash; it stops at the local authorization gate and prints the source-manifest digest. Then resume with that digest only after those source bytes are authorized for external processing:

```bash
vessel-reconstruct agent run data/examples/agent/spec.json \
  --out /tmp/marinaframe-live --policy live --max-policy-calls 6 --max-actions 6
# Read source_manifest_sha256 from the locally blocked task, then:
vessel-reconstruct agent resume /tmp/marinaframe-live --policy live \
  --authorize-data-sha256 EXACT_CAPTURED_HASH --max-live-requests 6
```

The default provider mode requires a verified applicable zero-cash account budget and available included usage. A denied budget read is a blocker; it does not silently select another admission mode. The explicitly selected `fresh_observed_included_allowance` pilot mode instead checks fresh included-usage meters and reserves a conservative full-context allowance with a fourfold margin. It is **not a provider-enforced zero-dollar spending cap**, cannot reserve against unrelated concurrent account usage, and requires an appropriately authorized experiment. Prior attempt reservations can be carried into the provider adapter rather than reset. Account billing settings are never changed.

The session's further six-generation experiment was rejected by automatic approval review because it would exceed the documented eight-call pilot and a hard zero-dollar account cap was unverified. No retry was made. One follow-up policy call was durably reserved without a provider response/usage receipt, so transmission and cost for that interrupted call are unconfirmed. Do not count it as a completed generation or successful CAD trial. The independently recorded completed calls are two capability smokes and four decisions in the first live harness attempt; all six returned Go billing and observed cost 0. Additional live work needs approval of a concrete bounded experiment or a verified applicable zero-cash guard.

### Drafting model (Rust controller, 2026-11-09)

`marinaframe run --model A[,B,...]` sets an ordered model list (run config `model`, then
`fallback_models`). Allowed (`rust-control/src/models.rs`, one table with each model's
transport): `claude-sonnet-5-5` (Claude subscription), `crouton-alpha-free` and
`deepseek-v4.1-flash` (OpenCode Go). Default of the CLI, the desktop app and
`scripts/run_round.py`: `claude-sonnet-5-5,crouton-alpha-free,deepseek-v4.1-flash` (founder
decision 2026-11-09). Claude and GPT models are never sent through OpenCode Go and never use an
API key; a test checks that no `claude-*`/`gpt-*` entry has the OpenCode Go transport.
`run_round.py` records the list in `round.json` and `digest.md`, and needs `OPENCODE_API_KEY*`
only when the list holds an OpenCode Go model.

- Fallback: when the transport answers HTTP 429, a rate-limit, quota or usage-limit error, or
  every Go key's usage window is exhausted, the next request uses the next model of the list.
  The controller records a `model_switched` event (from, to, request id, status, reason) and
  the state's `active_model`; `status` shows `models` and `current_model`. Other errors never
  switch.
- Receipts: `requested_model` is the request body's model and must be in the run's list;
  `returned_model` must equal it, else `provider_model_identity`; `endpoint` must be the
  model's transport endpoint (`https://opencode.ai/...` or `claude-cli:print:subscription`).

#### Claude subscription transport (`rust-control/src/claude_cli.rs`)

The provider worker runs the `claude` CLI (Claude Code 2.1.280, logged in on the Claude
subscription) once per request, with an argument vector (no shell):
`claude -p --model claude-sonnet-5-5 --effort low|high --tools "" --strict-mcp-config
--safe-mode --disable-slash-commands --no-session-persistence --input-format stream-json
--output-format stream-json --verbose --system-prompt <purpose prompt>`, plus
`--json-schema <tool, arguments, reason, notes>` for decisions. `--bare` is not used: it
refuses the subscription login.

- Input: the request body keeps the chat-completions form (hashed in the receipt). Its system
  message becomes `--system-prompt`; the last user message becomes one stream-json user
  message (text blocks and base64 PNG image blocks). Stream-json input takes user messages
  only, so earlier conversation turns go before it in ONE JSON-encoded block (an array of
  `{role, content}`, serialized by serde so quotes and brackets are escaped), framed by fixed
  texts saying the block is data, not instructions. Drawing or tool text inside it cannot
  forge a turn; the harness's instructions stay only in the system prompt.
- Environment: cleared, then HOME, USER, LOGNAME, LANG, LC_ALL, TMPDIR, a fixed PATH,
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS=<max_tokens>` and `DISABLE_AUTOUPDATER=1`. No OpenCode Go key,
  no `ANTHROPIC_*` variable. Working folder: the system temp folder.
- Executable: `MARINAFRAME_CLAUDE_BIN` (absolute path), else `/opt/homebrew/bin/claude`,
  `/usr/local/bin/claude`, `~/.local/bin/claude`, `~/.claude/local/claude`. Route checked
  2026-11-09: `/opt/homebrew/bin/claude` goes straight to the Anthropic API with the keychain
  login (`apiKeySource: none`); the Headroom proxy (`localhost:8787`) was not running and is not
  used (it is only in front of `claude` when `ANTHROPIC_BASE_URL` points at it, which the cleared
  environment prevents). `claude-raw` is not installed on this Mac.
- Bounds: the request wall time (`request_wall_seconds`) kills the CLI (`provider_cli_timeout`,
  outcome unknown); stdout above 256 KiB is refused; the CLI stays in the provider worker's
  process group, so the supervisor stops both. A missing CLI leaves the request not sent.
- Output check: the stream's `init` message must list no tool except `StructuredOutput` (the
  `--json-schema` carrier), no MCP server and `apiKeySource: none`, else
  `provider_cli_configuration`. `modelUsage` must name exactly the requested model. A
  `rate_limit_event` with status `rejected`, `api_error_status` 429 or a limit text ("hit your
  limit", "usage limit", ...) is `provider_rate_limited` (fallback); other CLI errors are
  `provider_cli_error`. The answer is `structured_output` (decisions) or `result` text, then
  parsed exactly as for OpenCode Go.
- Receipt: `http_status` 200 for a success result (else the CLI's `api_error_status`), usage
  `prompt_tokens` (input + cache write + cache read), `completion_tokens`, `total_tokens`,
  `cost` 0 (no per-request charge), `list_cost` = the CLI's `total_cost_usd` (API-price
  estimate), `billing_source: subscription`, `latency_seconds` around the CLI run, and
  `credential_selection` `{transport: claude_subscription, api_key: false}`. The stdout is the
  receipt body; the controller re-derives decision, model and usage from it.
- No temperature (the CLI has no option); `effort` low for normal calls, high with
  investigation thinking. Linux: the provider worker's 1 GiB address-space limit is inherited
  by the CLI; not yet checked there.
- Images: Sonnet 5.5 does not downsample at 1,568 px. Probe `work/claude-vision-probe`
  (2026-11-09): image tokens follow the area up to about 3.75 Mpx (2,048 x 512: 1,342 tokens;
  1,568^2: 3,139; 2,048^2 and 2,576^2: both 4,809), and 9 px text on a 2,048 px sheet read 12/12.
  So every image within the harness cap (2,048 px, 1 Mpx) reaches it at full size; the table
  keeps 2,048 px / 1 Mpx for all three models.
- Request settings per model (one table in `models.rs`): DeepSeek gets
  `thinking: {type: enabled|disabled}`; Crouton refuses `thinking` (HTTP 400) and gets
  `reasoning_effort` (`low` for normal calls, `high` with investigation thinking) and 4,096 extra
  `max_tokens` for its hidden reasoning (a 200-token probe without `reasoning_effort` returned no
  content). Both accept `response_format` json_object, temperature 0 and 32,768 `max_tokens`.
- Crouton notes: it reads images up to about 2,048 px per side (the controller caps images at
  2,048 px / 1 Mpx); it is slow; OpenCode Go does not count its image tokens and reports cost 0
  and no reasoning tokens. Sheet-setup and table-reading requests (`vision-request`,
  `read-table`) use the default model; build reviews inside a run use the run's current model.

## Replay and mocks

```bash
vessel-reconstruct agent transcript LIVE_TASK --out recorded-inputs.json
vessel-reconstruct agent replay recorded-inputs.json
```

Exact replay validates the frozen provider prompt/protocol, tool schemas, recorded observations, image bytes/hashes and decisions. It makes zero generation requests and executes zero CAD operations. It does **not** claim to reconstruct a fresh task with different IDs/timestamps, or to prove model quality. Transcript export requires the provider-bound receipts; the deterministic policy is compared by rerunning its source-only workflow instead.

`--policy scripted --script decisions.json` is a mock protocol mode accepting a bounded JSON decision list. Its receipts explicitly prohibit model-quality claims. Provider unit tests inject a transport and mark responses `mock_transport`; these never appear in live quality totals.

## Durable state, recovery and termination

Default task limits are 18 actions, 12 policy calls, 3 builds, 2 consecutive identical actions, 3 failed/rejected operations and 600 seconds of active wall time. Each parser/native operation also keeps its existing resource limits. Live pilot bounds are smaller. Legacy tasks with recorded live calls but missing original live-cap/prior metadata cannot dispatch further live calls. Offline inspection remains available. Resume preserves the original controller limits; neither a policy change nor an operator step resets counters. A wall-time timer propagates cancellation into the provider and native workers. An already dispatched network request may finish remotely after local cancellation, so its reservation is retained.

Task events record the source/domain state, request observations, image identities, decisions, sanitized usage, tool start/result, revision, rejected operations and termination. The mutable `state.json` is derived from the hash-chained events. A controller restart retains unknown in-flight request reservations and charges the elapsed interruption interval. If a native tool changed persistent domain state without completing its controller checkpoint, the task stops for investigation; it is not silently adopted. Preserve it and begin a separately recorded task from reviewed inputs. Evidence hashes cannot protect against a privileged actor rewriting all files and hashes together.

Oversized combined observations are handled explicitly. Duplicate summaries and non-display artifact metadata may be omitted while complete original observations remain in the event store. Alternatives for any displayed section are kept together. If the context is still too large, the model receives an explicit size diagnostic and must reinspect smaller groups or abstain; omitted alternatives never become an apparent unique contour.

Terminal outcomes include `awaiting_human_review`, `blocked`, `provider_failed`, `budget_exhausted`, `cancelled` and `no_progress`. Every outcome has `engineering_approved=false`. A failed current revision never inherits an older candidate's success.

## Execution context and artifact publication

The continuation reproduced a managed-workspace interference problem on the exact reviewed 0.2 engine. Runs verified immediately, then deleted transaction artifacts reappeared about one second later; one failed manifest even captured a transient `.rsync-tmp` path. Four of four workspace probes eventually failed integrity, while four of four `/tmp` probes remained intact. Three completed-only imports also stayed intact across another tool call. Ptrace was denied, so the external synchronizing process is not identified. This remains an unresolved environment issue.

Use temporary active task directories in this environment. Only after a task is terminal, copy its complete directory to a fresh artifact destination, then verify both copies. Do not delete reappeared transaction files, ignore a failed manifest, filter unknown inventory entries, or overwrite a failed run. The 0.2 engine safety gates are unchanged. See `AGENT_PUBLICATION_INVESTIGATION.md` for exact attempts and evidence.

## Evaluation boundaries

The original 47-case suite is development/regression data after inspection. It contains 42 numeric tasks and five expected refusals; clean/degraded variants share underlying hulls. The new final set is separately generated and managed by an independent evaluator, with opaque input IDs, frozen hashes and evaluator-only references. Inference processes receive source-only temporary directories, and targets are read only by the scorer after inference ends. This is procedural separation, not an OS-enforced claim that privileged code could never read other files.

Geometry consistency against the same extracted trace is not independent hull accuracy. Reports separate source-pixel support, actual STEP round-trip/cut consistency, external-reference volume and local-shape error, expected refusals, false rejections, publication failures, calibration supplied by a person, and explicit operator interventions. No pretrained weights were updated; no training, fine-tuning, or retrieval-augmented inference was performed.
