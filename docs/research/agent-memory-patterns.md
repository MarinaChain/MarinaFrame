# Agent memory patterns for the MarinaFrame controller (W18 input)

Date: 2026-11-08. Scope: patterns we can build INTO the Rust controller
(`rust-control/src/controller.rs`) with no framework dependency.
Sources are primary docs and source repositories. Items I could not confirm
are marked UNVERIFIED. No third-party code is copied here.

Our constraints, used as the fit test for every pattern:

- C1. The hash-chained event log is the only source of truth. Replay after a
  restart must rebuild byte-identical model requests.
- C2. Model output is untrusted. The controller writes every evidence summary.
  The model never writes memory.
- C3. DeepSeek returns one JSON object. We cannot rely on native tool-call
  blocks, thinking blocks, or vendor-side compaction.
- C4. At most 4 images per request.

Short conclusion: the vendors mostly do compaction by asking an LLM to write
a summary. That breaks C1 (not deterministic) and C2 (model-written). The
parts we can reuse are the STRUCTURES: a session tree with a "first kept
entry" cut marker, clear-old-tool-results with a placeholder, a fixed summary
schema, and isolated sub-contexts that return a short report.

## 1. pi (badlogic/pi-mono, now github.com/earendil-works/pi, MIT)

Packages: `pi-ai` (provider API), `pi-agent-core` (loop and state),
`pi-coding-agent` (CLI). Repo: https://github.com/badlogic/pi-mono

Session format (`packages/coding-agent/docs/session-format.md`):

- Append-only JSONL. Line 1 is a header (`type: session`, `version: 3`, id,
  cwd, optional `parentSession`). Every other line has `type`, `id` (8-char
  hex), `parentId`, ISO `timestamp`.
- The parent links form a TREE. Branching is "move the leaf pointer", with no
  file copy. A `/tree` jump can append a `branch_summary` entry.
- Entry types: `message` (roles system, user, assistant, toolResult),
  `model_change`, `thinking_level_change`, `usage`, `compaction`,
  `branch_summary`, custom entries.
- A `toolResult` message holds `toolCallId`, `toolName`, `content` blocks
  (text or image, base64 plus mimeType) and `isError`.
- Prompt and tool set are themselves logged as system messages that patch
  named `sections` and list `toolsAdded` / `toolsRemoved`. Replaying them in
  order gives the current prompt. This is a good replay design (C1).
- Source: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/session-format.md

Compaction (`packages/coding-agent/docs/compaction.md`):

- Trigger: `contextTokens > contextWindow - reserveTokens`.
  Defaults: `reserveTokens = 16384`, `keepRecentTokens = 20000`, enabled.
- Cut point: walk backward from the newest entry, add token estimates until
  `keepRecentTokens` is reached. Valid cuts are user, assistant, bash and
  custom messages. NEVER cut at a tool result, so a result stays with its call.
  If one user span is bigger than the budget, cut inside it at an assistant
  message and write two summaries (history, and span prefix), then merge.
- Result: a `compaction` entry with `summary`, `firstKeptEntryId`,
  `tokensBefore`, optional `usage`, and `details` (`readFiles`,
  `modifiedFiles`). Old entries stay in the file but are skipped when the
  request is built. The next compaction starts from the old
  `firstKeptEntryId`, so earlier kept messages are summarized again.
- Summary sections: Goal; Constraints and Preferences; Progress (Done, In
  Progress, Blocked); Key Decisions; Next Steps; Critical Context; then
  file lists. Branch summaries stop after Next Steps.
- Pruning for the summarizer: each tool result is cut to 2000 characters with
  a "N characters truncated" marker. Thinking blocks are dropped.
- Source: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/compaction.md

Size claims: the author says system prompt plus tool definitions are below
1000 tokens. Default tools: `read`, `bash`, `edit`, `write` (4). `grep`,
`find`, `ls` exist but are off by default. In the 2025-11 post he said
compaction was not yet built and not missed; it was added later.
Source: https://mariozechner.at/posts/2025-11-30-pi-coding-agent/

Fit:

- ADOPT: append-only log with `id`/`parentId`; `firstKeptEntryId` cut marker;
  never split a tool call from its result; prompt/tool patches as log events;
  raw entries stay in the log while a projection builds the request.
- ADOPT: compaction as a LOG EVENT that stores the summary. Replay then reads
  the stored summary and never regenerates it (C1).
- ADAPT: pi's summary is LLM-written. We keep the section layout but fill it
  from structured fields the controller already verified (C2).
- Our model is a JSON-object responder, so "tool call + toolResult" becomes
  our own `action` + `observation` event pair.

## 2. Claude Code, Claude Agent SDK, Anthropic API

Context editing, `clear_tool_uses_20250919` (beta header
`context-management-2025-06-27`):
Defaults: `trigger` 100,000 input tokens (or a `tool_uses` count); `keep` 3
most recent tool use/result pairs; `clear_at_least` none; `exclude_tools`
none; `clear_tool_inputs` false (calls stay, only results are cleared).
Cleared results become a placeholder. Clearing invalidates the prompt cache
prefix, so `clear_at_least` exists to make each clear worth it. The response
lists `applied_edits` (cleared counts). A separate `clear_thinking_20251015`
keeps the last 1 thinking turn by default.
Source: https://platform.claude.com/docs/en/build-with-claude/context-editing

Server compaction, `compact_20260112` (beta header `compact-2026-01-12`):
Default trigger 150,000 input tokens, minimum 50,000. The API writes a
`compaction` block (summary inside `<summary>` tags: state, next steps,
learnings). On replay, the API ignores every block before the compaction
block. Custom `instructions` REPLACE the default prompt. `pause_after_compaction`
lets the client reinsert recent turns. A `null` summary means keep the
originals. On-demand and keep-recent-turns variants also exist.
Sources: https://platform.claude.com/docs/en/build-with-claude/compaction-threshold
and https://platform.claude.com/docs/en/build-with-claude/compaction

Claude Code: sessions are plaintext JSONL under `~/.claude/projects/`; resume
appends, fork copies to a new id. Auto-compaction writes a summary that keeps
requests and key snippets; early detailed instructions can be lost, so
durable rules go in CLAUDE.md. It stops after a few repeated attempts when
one huge output refills context ("thrashing" guard). Subagents may set
`autoCompactWindow` (100,000 to 1,000,000). The exact auto-compact percentage
is UNVERIFIED (not stated on the pages I read).
Source: https://code.claude.com/docs/en/how-claude-code-works

Memory tool `memory_20250818`: client-side. Claude emits commands `view`,
`create`, `str_replace`, `insert`, `delete`, `rename` under `/memories`; the
application executes them against its own storage. Docs require path
validation (reject `..`, URL-encoded traversal, check the canonical path),
size caps, and expiry. Docs say pair it with context editing or compaction:
memory keeps what must survive clearing. The docs also describe a
multi-session pattern: a progress log plus a feature checklist, updated at
session end and read at session start.
Source: https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool

Subagents: each has its own context window, system prompt and tool
allowlist. A non-fork subagent sees only the delegation message. ONLY its
final report returns to the parent; its tool output stays in its own context.
Claude Code scans the returned report for tag-like text before the parent
reads it (it does not strip content).
Source: https://code.claude.com/docs/en/sub-agents

Fit:

- ADOPT: the clear-old-results shape (`keep` last N, placeholder text, keep
  the call, drop the payload, never clear listed protected tools). We run it
  in the controller as a pure function of the log, so it is deterministic (C1).
- ADOPT: subagent idea as "investigation step with isolated context". Only a
  controller-validated short report (typed fields) enters the main thread.
- ADOPT: the multi-session "progress log plus checklist" idea, but as
  controller-written state (see section 6), not a model-edited file.
- AVOID: the memory tool as designed. It lets the model write memory (breaks
  C2) and needs native tool calls (C3).
- AVOID: vendor server compaction. It is not available for DeepSeek, and a
  server summary is not reproducible on replay (C1).

## 3. OpenAI Agents SDK

Sessions (https://openai.github.io/openai-agents-python/sessions/):

- Before each run the runner loads history and prepends it to new input;
  after the run it saves the new items. `SQLiteSession` orders rows by an
  insertion id. Other backends: Redis, SQLAlchemy, Mongo, Dapr, OpenAI
  Conversations. `AdvancedSQLiteSession` adds branching and usage stats.
- Trimming: `SessionSettings(limit=N)` keeps the N most recent ITEMS; the
  default is `None` (all). `session_input_callback` receives copies of
  history and new input and returns what the model sees; only new-turn items
  are persisted, so filtering never rewrites stored history. A separate
  `call_model_input_filter` runs just before the model call.
- `OpenAIResponsesCompactionSession` wraps a session and calls the
  `responses.compact` endpoint after turns when `should_trigger_compaction`
  says so (mode `auto` by default). The default threshold is not stated in
  the docs (UNVERIFIED). The SQLite backend does not verify row integrity.

Handoffs (https://openai.github.io/openai-agents-python/handoffs/):

- A handoff appears to the model as a tool (`transfer_to_<agent>`). By
  default the next agent sees the whole history. An `input_filter` can edit
  it; built-in `remove_all_tools` strips tool items. `nest_handoff_history`
  (off by default, beta) folds earlier history into a
  `<CONVERSATION HISTORY>` summary block.

Fit:

- ADOPT: the separation "stored history is immutable; a view function builds
  the model input". This is the core of deterministic replay. Our view
  function is: log -> projection -> request, with no hidden state.
- ADOPT: a hard item limit as the simplest safety net (last N events), in
  addition to token budgets.
- AVOID: count-only trimming as the only rule. It can cut an action from its
  observation.
- AVOID: handoff-by-model-tool. A handoff would be a controller state change
  (phase transition), not something the model triggers freely.

## 4. Letta (MemGPT)

Docs: https://docs.letta.com/guides/agents/memory-blocks and
https://docs.letta.com/guides/agents/architectures/memgpt

- Core memory = "memory blocks" inside the context window, always visible,
  placed in the prompt in an XML-like `<memory_blocks>` section. Each block
  has `label`, `description` (guides how the agent uses it), `value`, and a
  character `limit` (examples use 4000 and 5000; no default stated). Blocks
  can be `read_only`. Writing `value` replaces the whole block, so the last
  writer wins.
- Recall memory = full message history stored outside the window; searched
  with `conversation_search`. Archival memory = long-term store outside the
  window with `archival_memory_insert` / `archival_memory_search`.
- When the window fills, older messages are compacted into a recursive
  summary and the full history moves to recall storage (from a search
  snippet of the Letta architecture page; thresholds are UNVERIFIED).

Fit:

- ADOPT: a small set of labeled, size-limited, read-only-to-the-model blocks
  that the controller always renders at a fixed place in the prompt
  (for example `task`, `verified_facts`, `open_questions`, `rejected_paths`).
  Block text is rendered from event data by controller code (C2). Fixed order
  and a hard character cap make replay stable (C1).
- ADOPT: "recall" = the event log itself. The model may ask the controller
  for an older event by id through a verified read action; the controller
  returns a bounded excerpt.
- AVOID: model-edited blocks and archival semantic search (embeddings are not
  deterministic across versions, and add a dependency). Last-writer-wins
  edits by the model are also unsafe.

## 5. Images in long multimodal histories

I found no first-party vendor doc on this. Evidence is community practice:

- TanStack AI computer-use harness: keeps the newest 3 screenshots in full
  (`keepScreenshots`), sends older ones as a 1x1 image.
  https://tanstack.com/ai/latest/docs/harness/computer-use.md
- Practice guides: keep the latest 2 to 3 images, replace older image blocks
  with a text marker plus a running text summary.
  https://callsphere.ai/blog/claude-computer-use-patterns-prompts-tools-context
  (secondary source, low authority).
- arXiv 2603.26041 reports a recency effect for GUI agents: more budget for
  recent screenshots, compression for older ones, with little loss.
  https://arxiv.org/pdf/2603.26041 (not read in full; details UNVERIFIED).
- pi stores images inline in `toolResult` content (base64 plus mimeType);
  its compaction summarizer sees only text.

Fit for C4 (our limit is 4 images per request, so the budget is tiny):

- ADOPT: image budget as a deterministic rule. Each image has a stable id
  (content hash, plus crop/region name). The request builder includes images
  only for the current observation, plus at most K older ones chosen by a
  fixed priority. Everything else is replaced by a text line such as
  `[image img_3fa9 (hull profile, crop 2 of 4) not attached; request
  re-attach by id]`.
- ADOPT: a verified `request_image(id)` action. It takes an image slot only
  if one is free this turn; the controller decides which slot is evicted.
- ADOPT: store a controller-written text description per image (measured
  facts from verified tools, not model prose), so evicted images stay useful.
- AVOID: a 1x1 placeholder image. It still counts toward the 4-image limit.

## 6. Proposed shape for the controller (derived, not a vendor pattern)

Each model request is built by a pure function of the log:

1. System prompt (fixed, versioned; its hash is logged).
2. Memory blocks rendered from log projections (task, verified facts,
   rejected hypotheses, open questions, budget left). Hard caps per block.
3. Compaction summary (latest `compaction` event), if any.
4. Recent window: events from `first_kept_event_id`, as action/observation
   pairs. Observations older than the last K pairs are replaced by a
   one-line placeholder with the event id (clear-old-results pattern).
5. Current observation JSON plus images chosen by the image budget rule.

Compaction trigger: estimated request size above a threshold computed by the
controller (suggest 60 to 70 percent of the DeepSeek context limit, tuned on
real runs; pi uses window minus 16k, Anthropic uses 150k of a larger window).
On trigger the controller appends one `compaction` event holding the
rendered summary, `first_kept_event_id`, `tokens_before`, and a digest of the
events it covers. Replay reads that event; it never calls a model.

The token estimate must be deterministic: use a fixed chars-per-token rule,
not a live tokenizer response, and log the number.

## 7. Ranked list for W18

Adopt, best first:

1. Immutable log plus pure projection (OpenAI session view, pi tree). Request
   = f(log). Add a test: replay the log, compare request bytes.
2. Controller-written compaction event with `first_kept_event_id` (pi). Never
   cut between an action and its observation. Summary text comes from
   verified fields in a fixed schema (pi section names as a template).
3. Clear-old-observations with placeholders and event ids (Anthropic
   `clear_tool_uses`): keep last N pairs (start with 3, their default), keep
   protected categories (verified measurements, rule outcomes).
4. Fixed-order, size-capped, read-only memory blocks (Letta layout, without
   model writes).
5. Image budget with stable ids and a re-attach action (community practice;
   our 4-image limit makes this mandatory).
6. Isolated sub-investigation that returns a typed short report (Claude Code
   subagents). The controller validates the report schema before it enters
   the main thread and scans text fields for injection markers.
7. Hard cap on events per request plus a thrash guard: stop compacting after
   a few attempts when one observation refills the window (Claude Code).
8. Log prompt version, tool set and compaction events as patch events
   (pi system-message sections) so prompt changes replay correctly.

Avoid:

- Model-written summaries or model-edited memory (breaks C2; this covers the
  Anthropic memory tool and Letta self-editing blocks).
- Vendor server-side compaction or LLM-regenerated summaries on replay (C1).
- Embedding or semantic archival search in W18 (non-deterministic, adds a
  dependency).
- Count-only trimming (OpenAI `limit=N`) without pair integrity.
- Placeholder images that still use an image slot.
- Relying on native tool-call or thinking blocks (C3).
- Letting the model trigger phase changes or handoffs directly.
- Rewriting history in place. Always append; project at read time.

## 8. Open questions for the team

- DeepSeek context limit and real token cost of our images: measure, then set
  the compaction threshold.
- Which verified fields are "protected" and never cleared.
- Hash chain: should a compaction event cover the hashes of skipped events?
  Recommend yes (store a digest of the span).
- Letta default block limits and the OpenAI default compaction threshold were
  not found in docs; do not copy numbers for them.
