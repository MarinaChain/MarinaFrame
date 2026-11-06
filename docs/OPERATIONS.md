# Local workbench operations

## Supported profile

MarinaFrame supports an **authenticated, single-user, loopback-only Linux research workbench**. The ordinary reconstruction path is offline after its dependencies are installed. Its queue and subprocess boundary make local work bounded, cancellable and recoverable; they do not turn document parsers or the CAD kernel into an operating-system sandbox. A resulting model still requires source review and qualified engineering assessment.

The tested packaging profile is Linux/Python 3.12 with the pinned native dependencies documented in the repository's environment and validation records. The process supervisor requires Linux procfs, POSIX resource limits, process groups and `prctl`; atomic run publication requires Linux `renameat2`. Namespace-aware process lookup supports the tested case where procfs is mounted from an outer PID namespace. The synchronous Python `pipeline.reconstruct()` API is caller-managed: use `isolation.run_isolated()` or the CLI/server for native resource limits.

Allow one active native reconstruction. A practical local host should provide at least 2 CPU cores, 8 GiB of RAM and several GiB of available disk space, with a dedicated artifact directory. These are operating assumptions, not a measured guarantee that every admitted document completes. See the validation artifacts for actual runtimes/RSS, and preserve the bounded default limits when evaluating unfamiliar inputs.

## Start and authenticate

```sh
vessel-reconstruct serve --artifacts artifacts --host 127.0.0.1 --port 8765
```

Open the **session URL printed by the process**. It contains a random token in the URL fragment, which is not sent in an HTTP request or referrer. The browser removes the fragment, exchanges the token once, and receives a host-only `HttpOnly; SameSite=Strict` cookie. The bootstrap link expires after 10 minutes and the session after one hour. Reloads reuse the cookie; restart the service and use its newly printed link to obtain another session. Do not publish the console link.

Only `127.0.0.1`, `localhost` (normalized to IPv4 loopback), and `::1` are accepted bind values. Remote addresses and `0.0.0.0` are refused before queue creation. The exact configured loopback authorities, including the actual port, form the Host/Origin allowlist. Matching two attacker-controlled headers does not grant access. API reads require a session; writes also require the session CSRF token. Static application assets contain no run data and may load before authentication. Cookie transport is local HTTP; this is not a TLS-authenticated remote identity profile. Reverse proxying, public exposure and distinct user accounts are unsupported.

An authenticated local session can inspect this artifact root's admitted runs. Sessions do not represent distinct tenants or authenticated professional identities. Raw source and exports are protected by the same local read boundary. Failed verification, staging paths, symbolic links, traversal and undeclared files are rejected. New run files must pass the versioned manifest and consistency checks; a local manifest is not a digital signature. Legacy records may appear in inventory, explicitly unsealed; replay them into a new directory before downloads or snapshots.

## Defaults and admission

| Boundary | Default |
| --- | --- |
| Concurrent native jobs | 1 |
| Receiving + queued + running jobs | 4 total |
| Local state history | 2,000 jobs; archive to a new root when full |
| Artifact root admission budget | 2 GiB, including existing content and conservative reservations |
| Free disk reserve | 256 MiB after reservations |
| Worker reservation | Source bytes plus 256 MiB of potential output |
| Primary / reference upload | 20 MiB / 12 MiB |
| Primary + reference bytes | 32 MiB |
| Per-source pixels | 16 million; longest dimension 20,000 pixels |
| Combined source pixels | 32 million |
| Estimated decoded bytes | 128 MiB/source and 256 MiB combined, using 8 bytes/pixel |
| PDF resolution | Finite 36–300 DPI |
| PDF pages / dimensions | At most 64 pages; every page bounded to 14,400 points per dimension |
| Selected PDF raster | Same pixel/dimension/decoded budgets as a raster image |
| Raster frames | One selected frame; multi-frame files must be split explicitly |
| Declared sections / traced ROI rows | 300 / 4 million aggregate |
| OCR cells | 512 across the whole job |
| Enlarged OCR crop | 4 million pixels/cell and 32 million combined, including padding |
| Worker wall / CPU | 180 s wall; 120 s CPU soft limit, 121 s hard limit |
| Worker address space | 4 GiB per process |
| Individual output file | 128 MiB |
| Aggregate run/staging output | 256 MiB, checked during execution and after exit |
| Open descriptors / core dumps | 64 / disabled |
| Native library threads | One (`OPENBLAS`, `OMP`, `MKL`) |
| HTTP connections | 16 concurrent; excess connections receive 503 |
| HTTP request lifetime | 20 s total, including slow headers/body and response |
| JSON API body | 2 MiB; bounded depth/item counts, no duplicate keys or nonfinite numbers |
| Compatibility JSON upload | 46 MiB, one body in progress at a time |
| Receiving upload expiration | 120 s from reservation |
| Terminal input spool retention | 24 h |
| Inventory / size walks | Bounded 500 run listings, 4,096 directories/files respectively |

A document's file size does not predict its decoded memory use. File signatures only route uploads; the HTTP process never invokes image/PDF parsers. A resource-limited worker validates metadata and combined work before any preview or full decode. Individual header/metadata parsers can themselves be complex, which is why preflight still runs in the isolated process. ROI and contour/CAD complexity limits provide additional gates.

The limits are explicit Python configuration (`SourcePolicy`, `WorkerLimits`, `JobQueue` options), not request-controlled settings. Changing one limit requires testing the corresponding CPU/RAM/disk assumptions. The defaults are conservative rejection bounds, not a promise that every document below them is supported. An OCR job can hit the overall wall budget before its maximum cell count, and it must then remain interrupted/failed rather than inventing remaining cells.

The queue reserves capacity **before** source spooling. A full queue returns 429; disk/history admission returns 507. Receiving jobs hold reservations and expire without requiring another request. A queue/root has one controller enforced by an OS file lock. SQLite uses WAL and full synchronous commits; corrupted state fails closed instead of silently resetting history.

## Job lifecycle and storage

```text
receiving -> queued -> running -> succeeded | blocked | failed
                                | cancelled | timed_out | resource_limited | interrupted
```

This sequence is documentation, not an additional success criterion. `succeeded` means a fully verified `review_required` inference record was committed, never engineering approval. `blocked`, `failed`, `cancelled` and `interrupted` records remain export-free. The queue reports timeout/resource-budget outcomes separately even where the recovered inference record uses `interrupted` as its evidence state.

Private control state is under `artifacts/.workbench/`: SQLite, the controller lock and `inputs/<job-id>/`. It is created with private permissions. Browser-supplied file paths are replaced by fixed source names, original upload hashes are recorded, and the exact queued specification is separately hashed. The worker rechecks those bytes before inference. Final runs appear at `artifacts/runs/<job-id>/`; that destination does not exist until atomic publication. Transaction staging and recovery directories remain private and are never served.

The worker receives an explicit environment allowlist, excluding inherited provider/API credentials, and no request can supply a command. It has its own process group, inherited native resource limits, and parent-death termination. Cancellation sends TERM followed by KILL to the owned process group, including ordinary OCR descendants. Restart recovery uses PID birth identity and a random inherited ownership marker; it does not blindly signal a reused PID. Resource limits are per process, not aggregate cgroup limits. Native code that deliberately changes process groups, arbitrary code execution, filesystem/network containment and malicious same-user processes require a stronger sandbox and remain outside this local profile.

Cancellation is best effort until publication. If a durable, unreserved and fully verified final record already exists when cancellation or worker failure arrives, **the completed publication wins**. The job reports its actual result status plus `publication_reconciled: true` and its original `worker_state`. An aggregate output-budget violation never receives this reconciliation: the new final output is hidden and its geometry/authoritative success files are stripped. While a queue-owned job is still running, and for unconfirmed failed jobs, the HTTP server does not expose successful CAD from a discoverable final directory.

## Streamed API and retry semantics

All `/api/*` calls require the session cookie except the one-time bootstrap exchange. Mutations send `X-MarinaFrame-CSRF`, returned by `POST /api/session` or authenticated `GET /api/session`. HTTP requests require a single exact `Content-Length`; chunked request framing and duplicate lengths are refused. The browser supplies lengths for Blob uploads. Uploads and downloads copy 64 KiB chunks; no whole uploaded document is decoded in the HTTP process.

1. `POST /api/uploads` with `{ "spec": {...}, "sources": { "primary": {"bytes": N, "sha256": "..."}, "reference": {...} } }`. Omit `reference` unless a station reference is declared. Optional `Idempotency-Key` contains 8–128 ASCII letters/digits/underscores/hyphens.
2. `PUT /api/jobs/<id>/sources/primary` (and `/reference` if declared), with `application/octet-stream` and the exact reserved bytes. A source's SHA-256 and size must match before promotion from its partial file.
3. `POST /api/jobs/<id>/submit` with `{}` after all sources arrive. The rewritten spec is committed and the job enters the durable queue.
4. `GET /api/jobs/<id>` to inspect state and timing/resource metadata; `POST /api/jobs/<id>/cancel` with `{}` to request cancellation.

Repeating an idempotency key with identical spec/descriptors returns the original job and state, including a terminal job. The same key with different content returns 409. Repeating a complete source upload while still receiving is harmless if its hash/size match; queued inputs cannot be replaced. Repeating submit returns current state. Retry an unfinished reservation through its existing ID, or cancel it and use a new key. A new submission is a new immutable inference attempt; an existing final run is never overwritten.

`POST /api/reconstruct` remains a bounded compatibility endpoint for base64 JSON clients and uses the same queue and source gates. The browser uses the streamed protocol. A failed compatibility upload cancels its reservation. A disconnected streamed upload expires after its reservation deadline and cannot publish a partial source.

Other read endpoints: `/api/runs`, `/api/run/<encoded-run-id>/<declared-file>`, and `/api/review/<encoded-run-id>`. Review state is derived from the checked review-event chain, separate from immutable `result.json`. A portable snapshot embeds a copy of that current review state and replay spec. It stays offline, has no login token and does not gain authority from being a single HTML file.

## Liveness, readiness, diagnostics

Authenticated `/api/health` reports controller liveness, worker-thread state, queue depth, active age, available slots, free disk, admission blocker and the most recent controller error code. `/api/ready` returns 503 when the worker is unavailable, overdue, saturated, stopping or storage/history admission would fail. A live HTTP process is not sufficient readiness. The default capacity check reserves for a maximum-sized next job, so readiness can conservatively refuse while a smaller explicit reservation would fit.

Durable job fields include queued wait, elapsed worker time, result status and sanitized error codes. A normal worker receipt reports wall time, CPU time including waited OCR children, peak worker RSS and child peak RSS. Abrupt kill may prevent a receipt; missing resource fields mean unavailable telemetry, not zero resource use. Queue state events use job IDs, states and codes; source contents, raw HTTP paths, cookies, bootstrap credentials and provider keys are excluded from logs. To consume structured state logs programmatically, configure Python logging for `vessel_reconstruction.jobs`; the SQLite events table remains durable regardless of console logging.

Native memory is limited by address space, not by RSS. RSS is observed after completion; its maximum and the limits should not be conflated. Peak child RSS is a separate maximum and cannot be summed into accurate process-tree peak memory. See the worker receipt definition before comparing measurements.

## Shutdown and restart

Stop the local server with Ctrl-C. New connections stop, the active worker receives a bounded process-group stop, and queued jobs remain on disk. Receiving uploads and any interrupted active job become explicit `interrupted` records on the next startup. A running job is not silently replayed: recovery quarantines private partial work, removes unpublished geometry and emits export-free interruption evidence when storage is writable. Queued jobs resume after their input hashes are checked. Terminal jobs remain terminal.

If storage fails, the system cannot guarantee a new durable error record. The controller returns a sanitized storage error; discoverable staging/reservations remain recoverable. Restore writable space before restarting. Do not delete active locks or edit queue rows to force a success. An unexpected live controller lock means another process owns this root; stop that process normally before attempting recovery.

Temporary source spools for terminal jobs expire after 24 hours. This does **not** remove retained source evidence from completed runs or erase spec metadata from SQLite. Final evidence, job history and quarantines are not automatically deleted; archive the artifact root and start a new one when the disk/history budget fills. Retention is therefore explicit preservation of completed evidence rather than silent data loss. Consider the root sensitive and keep its backups private.

## Quiescent backup and restore

Stop the workbench first. Use a new backup directory outside the source artifact root. The queue checks that no receiving/running work is active, copies the artifact tree and inputs, and uses SQLite's backup API for a consistent database. Its controller lock and WAL files are not copied as control state. Symbolic links anywhere in the artifact root are refused before backup, so an external target is never copied implicitly.

```python
from pathlib import Path
from vessel_reconstruction.jobs import JobQueue

queue = JobQueue(Path("artifacts"), start_worker=False)
try:
    queue.backup(Path("backup-2026-11-07"))  # must not already exist
finally:
    queue.close()
```

Preserve that backup, copy it to a new restore location, and start `vessel-reconstruct serve --artifacts restored-artifacts`. The same package/environment should be used initially. Completed immutable evidence is verified at access; queued source/spec hashes are checked before resuming. Validate important run manifests and representative snapshots after restoration. The automated regression actually backs up and opens a restored database, verifies queued bytes and checks a retained artifact; it does not claim encrypted backups, remote object-store durability, or production disaster-recovery certification.

## Migration and rollback

Keep old artifacts intact. Legacy schema-1 records are explicitly unsealed; they are not upgraded by editing a manifest. Replay source/spec into a new destination to create a schema-2 run. Existing completed directories cannot be overwritten. New SQLite queue state is private to the local workbench and is not imported from the old in-memory job list. Jobs lost before this migration cannot be reconstructed from missing memory.

To roll back application code, stop the controller and preserve the entire artifact root first. Use a separate legacy artifact root with old code; do not let the unauthenticated legacy server expose new private queue/evidence directories. A rollback does not downgrade a new manifest or reinterpret an unsuccessful record as success. Restore with the matching newer version for full new-state verification.

## Demonstrated scope and remaining work

The runtime tests exercise hostile Host/Origin pairs, read/write authentication, CSRF, request deadlines, streamed source hashing, traversal/symlinks, quota/saturation, idempotency, duplicate/nonfinite JSON, malformed legacy inventory, exact queued-spec binding, real resource-limited subprocesses, process-tree stop, namespace-aware orphan recovery, durable queue restart, input retention and backup/restore. Independent tests cover publication/cancellation races and post-exit output-budget enforcement.

These checks support a more reliable local research tool and a basis for a controlled pilot with supervision. They do not establish unattended production operations, a remotely authenticated service, adversarial OS isolation, expert-validated source interpretation, or engineering-qualified use.
