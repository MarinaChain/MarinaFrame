# Final Python verification for MarinaFrame 0.4.0

The complete Python source suite passed **670 tests in 112.90 seconds**, with zero failures, errors or skips. The separately built non-editable wheel passed the installed engine smoke. The legacy Python-agent smoke passed unchanged when executed in `/tmp`; its earlier workspace-output failure remains preserved and is described below. These are Python engine and comparison/fallback checks. They are not the Rust controller's acceptance result.

## Environment and artifacts

Verification used `/tmp/marinaframe-v04-release-env`, a fresh Python 3.12.14 virtual environment with system site packages disabled. The 55 base-lock entries and six annotation-lock entries contain 59 unique packages; every installed version matched, with no missing packages or extras before installing this project. `pip check` passed before and after the non-editable install.

The project was temporarily installed editable for the source suite, built with the locked build tools and `--no-isolation`, uninstalled, then installed from its wheel with `--no-index --no-deps`. An isolated `python -I` probe from `/tmp` confirmed version 0.4.0, imports from the environment's `site-packages`, and wheel archive metadata rather than an editable directory. The relevant installed and source code hashes match.

Wheel: `vessel_reconstruction-0.4.0-py3-none-any.whl`, 196,907 bytes, 38 archive files. SHA-256:

```text
7c2ac885d9c49fbe7478b6c1bcddc35f1ef90e3ae0e2edba8fa1cbb2749869fb
```

Full evidence is under `artifacts/v04/release/python-verification/`: commands, stdout/stderr logs, JUnit, dependency inventory, lock comparisons, before/after source hashes, wheel and its manifest, complete smoke outputs and the preserved unsuccessful task. The source/test/pyproject hash inventory was unchanged across the complete suite. No production code or test expectations were changed during this verification.

## Results

| Gate | Result |
| --- | --- |
| Exact locked dependency versions | 59 unique packages matched; no extras or mismatches |
| Full source test suite | 670 passed; 0 failed, 0 errors, 0 skipped; 112.90s |
| Wheel build and isolated installed identity | Passed; non-editable 0.4.0 import from `site-packages` |
| Installed engine smoke | 9 checks passed; 67.19s |
| First installed legacy agent smoke, active output in workspace | Failed closed at validation after a successful build/render; original task preserved |
| Same installed agent smoke, active output in `/tmp` | 6 checks passed unchanged; 12.35s; awaiting human review |
| Completed agent copy | 95 files, 3,394,129 bytes; 26 events and 22 artifact references verified |
| Optional old Python live-transcript replay | Not executed: the optional 0.3 transcript is absent from this checkout |

The nine engine checks were import/resources, dependency consistency, CLI help, procedural source generation, native reconstruction, verification, a `needs_information` review record, verification after review and snapshot export. The smoke also confirmed the review did not change the immutable result bytes.

The six legacy-agent checks were installed-module identity, procedural source generation, deterministic agent run, task verification, review export and status. The successful task has one build, zero operator actions, `awaiting_human_review`, `engineering_approved: false` and 26 events. It made no provider calls. Its head is:

```text
f52e3056a12c97c27f19b09cd2f94e70526d729ef0f2f07b511c7f6434095f2a
```

## Preserved publication anomaly

The first legacy-agent smoke used active output under the workspace. It built a candidate and rendered its STEP successfully, then twice rejected validation with `Candidate evidence changed or failed immutable-run verification.` The harness stopped at `no_progress` after seven actions and two rejections. It never approved engineering use.

The exact underlying refusal was the first publication guard in `verify_run`: a `.r0001-1bc870fa3ebb.run-lock` marker existed beside the completed `r0001-1bc870fa3ebb` run and an unfinished `.r0001-1bc870fa3ebb.staging-35c3f0585f71436eb2da847eaea6f73c` directory. The marker still recorded the `geometry_export_and_reload` phase. Its recorded modification time preceded the published result, while its change time followed publication. No matching worker process was found during the later read-only inspection. The original marker, stage, run, events and metadata remain untouched.

The six relevant installed/source modules had identical hashes. A separately labelled diagnostic copy containing only the published run bytes verified all 40 checks. That diagnostic copy was not used to recover or promote the original task; the original remains blocked by its publication marker. The unchanged installed smoke then passed with active output in `/tmp`, and only its completed output was copied into the workspace. The root cause of the first publication anomaly is not established by those observations. Independent controlled publication/reliability probes are recorded separately.

No guard was weakened, no marker was deleted and no test was rewritten. Subsequent active native runs use `/tmp`; completed evidence is copied and verified afterward. The completed agent copy was verified again across a later tool boundary, with the same event head and identical file inventory/hashes. Both check records are retained.

The source suite and native smoke phases held the global native admission lock while other CAD trials were paused. That window has been released. The release environment is left with the non-editable wheel installed for the separate installed Rust/worker acceptance check.
