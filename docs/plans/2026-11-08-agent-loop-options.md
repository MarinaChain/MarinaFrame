# Agent loop with memory: adopt a light framework, or build it into the harness?

Written 2026-11-08 after the sealed v2 head-to-head. Decision needed before W18.

## The gap

The DeepSeek investigator is stateless. Each request is `[system prompt, current observation + up to
4 images]` (`rust-control/src/controller.rs`, request builder). The model never sees its own earlier
messages, only a 12-step action list whose reasons were always `null` (bug, fixed in W17). In the
head-to-head, 270 of 288 LLM cases stopped because the model repeated an identical action.

What we need is a **bounded conversation loop**: the model's own past decisions and the tool results,
compacted when long, with images under a limit. Everything else that an agent harness gives (tool
execution, budgets, retries, receipts, sandbox) MarinaFrame already has.

## What must stay true in either option

- The Rust controller is the only authority: it executes and verifies every tool, keeps the
  hash-chained event log, receipts, budgets, key rotation and the native admission lock.
- Replay: a restarted task rebuilds exactly the same state from the event log.
- Model output is an untrusted claim; assignments stay open `model_choice` guesses;
  `engineering_approved` is always false; no gate changes.
- The desktop app is native (Tauri + Rust + Python workers). DeepSeek is the provider.

## Option A: adopt a lightweight agent framework

### A1. pi (`pi-agent-core` / `pi-ai`, Mario Zechner, MIT, TypeScript)

pi is a minimal coding agent in layers: `pi-ai` (multi-provider API), `pi-agent-core` (agent loop,
tool execution, state, sessions), and the CLI on top. The lower layers can be used alone.

- **For:** a real, small, well-regarded loop library; sessions and compaction already exist;
  multi-provider, so DeepSeek works; its philosophy (short system prompt, few tools) is a good lesson
  for us.
- **Against:**
  - It adds a Node runtime beside the Rust controller, in an app we made native on purpose.
  - Two state stores: the pi session and our event log. Replay, receipts and the audit chain would
    need the pi session to be derived from our log, or the two drift. Making pi follow our log removes
    most of what pi gives us.
  - Provider calls must stay inside the controller (key rotation, budgets, receipts, cost caps). So
    `pi-ai` would not make the calls, and `pi-agent-core` becomes a message-list manager calling back
    into Rust for every model call and every tool.
  - Its tools are coding tools (read, write, edit, bash); none apply. We would only use the loop
    skeleton.
- **Integration cost:** a sidecar process and IPC protocol, packaging Node in the app, a mapping of
  events to pi messages, and security review of a new dependency tree. This is more code than the
  loop itself.

### A2. NanoClaw (MIT, Node host + per-session containers, built on Claude Agent SDK)

NanoClaw is a personal assistant product: containers per agent group, its own memory files,
messaging channels (WhatsApp, Telegram, Slack and others).

- **Wrong class for this job.** It is built on the Claude Agent SDK (we run DeepSeek), it brings
  containers and chat channels we do not need, and its memory is free-form files, not an audited
  event log. Not recommended.

### A3. Other general agent SDKs

The same trade-off as A1, usually larger. They own the loop, the provider call and the memory, which
are the three parts that must stay in the controller.

## Option B: build the loop into the MarinaFrame harness (Rust controller)

- Build `messages` from the existing event log: per past step, an `assistant` message with the
  model's JSON decision (tool, arguments, reason, notes) and a `user` message with a compact result
  (status, error code and message, new view and candidate ids). The full current observation goes in
  the last message only.
- Token budget per request; keep the latest N steps verbatim and fold older steps into a summary that
  the controller writes from events (no model-written summary of evidence).
- Images: attach only new views (limit 4); older views are referred to by id and can be recalled.
- A progress line each turn: sections assigned / remaining, draft state, repeats refused.
- **For:** one source of truth; replay and receipts work unchanged; no new runtime or dependency; the
  provider path, keys and budgets do not move; estimated a few hundred lines of Rust plus tests.
- **Against:** we own compaction and its tests. Folding is deterministic and simple here, because the
  domain state (sections, candidates, views) is already structured.

## Comparison

| Criterion | A1 pi-agent-core | A2 NanoClaw | B Build into harness |
|---|---|---|---|
| Fixes the memory gap | Yes | Yes | Yes |
| Controller stays the only authority | Only with heavy adaptation | No | Yes |
| Replay from event log | Needs mapping both ways | No | Yes, by construction |
| Provider, keys, budgets unchanged | Must bypass `pi-ai` | No (Claude SDK) | Yes |
| New runtime / dependencies | Node + npm tree | Node + containers | None |
| Fits native Tauri app | Sidecar | Poor | Yes |
| Effort | Medium-high (integration) | High (wrong shape) | Medium (loop + tests) |
| What we reuse | Loop skeleton, ideas | Little | Existing event log and tools |

## Recommendation

**Option B**, and take two ideas from pi: keep the system prompt short and the tool list small (we
now send 16 tools and a ~3,000-character prompt), and treat the session as a tree we can branch from
for a retry. The decisive reason is architecture, not model quality: the loop, the provider call and
the memory are the parts that must stay inside the audited controller, and they are exactly what a
framework wants to own.

No spike of A1 is planned: the comparison does not depend on model behaviour, so a prototype would
not change the decision. If B's dev results (W18) are poor, the cause will be the loop design, and a
framework would not fix that.

## Next

W18 brief: `work/w17/w18-brief.md` (local). Measure W17 (stateless + notes) against W18 (loop) on the
same non-sealed dev cases. A new held-out split is required before any claim about the default.

Sources: [pi overview](https://agentic-ai.readthedocs.io/en/latest/AgentHarness/pi-dev/),
[Armin Ronacher on pi](https://lucumr.pocoo.org/2026/1/31/pi.md),
[NanoClaw](https://nanoclaw.dev/).
